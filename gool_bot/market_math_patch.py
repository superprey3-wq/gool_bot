"""Conservative prematch math plus confirmation-only Kambi context.

Flashscore/LSApp owns the actionable market and entry price. Kambi can confirm
an already-present exact line but can never fill a missing line or become the
primary. Prematch math may nudge rating but never creates a LIVE signal.
"""
from __future__ import annotations
import logging,re,time
import live_candidate_patch as lc
from kambi_live_odds import get_live_goal_totals
from match_history import fetch_match_history
from math_forecast import forecast_from_history

logger=logging.getLogger("market_math_patch");_orig_market=lc._market;_orig_evaluate=lc._evaluate;_orig_format=lc._format_strategy_signal
_MATH_CACHE={};_MATH_CACHE_SECONDS=900

def _norm(name):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(name or "").lower()).split())
def _team_rows(rows,team_name):
    team=_norm(team_name);out=[]
    for row in rows:
        home=_norm(getattr(row,"home",""));away=_norm(getattr(row,"away",""));hg=int(getattr(row,"home_goals",0) or 0);ag=int(getattr(row,"away_goals",0) or 0)
        if team and (team in home or home in team):out.append({"goals_for":hg,"goals_against":ag})
        elif team and (team in away or away in team):out.append({"goals_for":ag,"goals_against":hg})
    return out

def _math_forecast(match):
    now=time.time();cached=_MATH_CACHE.get(match.event_id)
    if cached and now-cached[0]<_MATH_CACHE_SECONDS:return cached[1]
    try:
        ctx=fetch_match_history(match.event_id,match.home,match.away,limit=8);home_rows=_team_rows(ctx.home_recent,match.home);away_rows=_team_rows(ctx.away_recent,match.away)
        result=forecast_from_history(home_rows,away_rows) if len(home_rows)>=3 and len(away_rows)>=3 else {}
    except Exception as exc:logger.info("MATH_FORECAST_FAILED %s: %s",match.event_id,exc);result={}
    _MATH_CACHE[match.event_id]=(now,result);return result

def _visible(row):
    try:return float(row.get("odd"))>1.001
    except (TypeError,ValueError,AttributeError):return False

def _confirm_kambi(recs,match):
    try:kambi=get_live_goal_totals(match.home,match.away)
    except Exception as exc:logger.info("KAMBI_CONFIRM_FAILED %s: %s",match.event_id,exc);return recs
    lookup={(str(x.get("scope")),float(x.get("line",-99))):x for x in kambi if _visible(x)}
    for r in recs:
        if str(r.get("primary_source") or r.get("source") or "") not in {"Flashscore/LSApp","LSApp"}:continue
        if r.get("line") is None:continue
        try:key=(str(r.get("scope")),float(r.get("line")));base=float(r.get("odd"))
        except (TypeError,ValueError):continue
        extra=lookup.get(key)
        if not extra:continue
        other=float(extra["odd"]);prices=list(r.get("source_prices") or [])
        if not any(str(x.get("source"))=="Flashscore/LSApp" for x in prices):prices.insert(0,{"source":"Flashscore/LSApp","odd":base})
        if not any(str(x.get("source"))=="Kambi/BetRivers" for x in prices):prices.append({"source":"Kambi/BetRivers","odd":other})
        r["source"]="Flashscore/LSApp";r["primary_source"]="Flashscore/LSApp";r["source_prices"]=prices;r["source_count"]=len(prices);r["bookmakers"]=max(int(r.get("bookmakers") or 1),len(prices))
        spread=abs(other-base)/min(base,other)*100 if min(base,other)>0 else 999;r["source_spread_pct"]=round(spread,2);r["market_consensus"]="CONFIRMED" if spread<=12 else "DISAGREE"
    return recs

def _market(entries,match,pressure):
    recs,market=_orig_market(entries,match,pressure);recs=_confirm_kambi(recs,match)
    # Do not reselect using an external price. Preserve the Flashscore-derived primary market.
    if market.get("available"):market["source"]="Flashscore/LSApp";market["primary_source"]="Flashscore/LSApp"
    return recs,market

def _evaluate(match,stats,pressure,goals,market):
    qualifies,route,master,scores,hazards,market=_orig_evaluate(match,stats,pressure,goals,market);fc=_math_forecast(match)
    if fc:
        p15=float((fc.get("overs") or {}).get("1.5",0) or 0);p25=float((fc.get("overs") or {}).get("2.5",0) or 0);bonus=0.0
        if p15>=80:bonus+=4
        elif p15>=72:bonus+=2
        elif p15<58:bonus-=2
        if p25>=62:bonus+=1
        elif p25<40:bonus-=1
        fade=1.0 if match.minute<=30 else .7 if match.minute<=60 else .4;bonus=max(-4,min(5,bonus*fade));scores["PREMATCH_MATH"]=max(0,min(100,50+bonus*10));master=max(0,min(100,master+bonus))
    return qualifies,route,master,scores,hazards,market

def _format_strategy_signal(match,pressure,stats,recs,goals,reason,route,master,hazards,market):
    text=_orig_format(match,pressure,stats,recs,goals,reason,route,master,hazards,market);fc=_math_forecast(match)
    if not fc:return text
    overs=fc.get("overs") or {};math_line=f"🧮 Прематч-математика: xG {float(fc.get('xg_total',0)):.2f} · ТБ1.5 {float(overs.get('1.5',0)):.0f}% · ТБ2.5 {float(overs.get('2.5',0)):.0f}% · ОЗ {float(fc.get('btts',0)):.0f}%"
    marker="\n🧠 Рейтинг сигнала:";return text.replace(marker,f"\n{math_line}{marker}") if marker in text else text+"\n"+math_line

lc._market=_market;lc._evaluate=_evaluate;lc._format_strategy_signal=_format_strategy_signal
