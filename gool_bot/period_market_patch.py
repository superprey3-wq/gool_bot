"""Separate whole-match best bet from live period goal markets.

Installed after live_candidate_patch. Keeps +1/+2 FT prices, chooses a separate
best FULL_TIME total for the card/text, and adds the exact first-half next-goal
price when the signal arrives before half-time.
"""
from __future__ import annotations
import logging
import unified_bot
import live_candidate_patch as lcp
from bovada_live_odds import get_all_full_time_over_odds, get_goal_total_odds, get_first_half_goal_odds

logger=logging.getLogger("period_market_patch")

def _ls_scope(entries,m,p,scope):
    return [dict(r,source="LSApp") for r in unified_bot._recommendations(entries,m,p) if r.get("scope")==scope]

def _whole_match_candidates(entries,m,p):
    goals=int(m.home_score)+int(m.away_score)
    rows_by_line={}
    for r in _ls_scope(entries,m,p,"FULL_TIME"):
        try:rows_by_line[float(r["line"])]=r
        except Exception:pass
    try:
        for r in get_all_full_time_over_odds(m.home,m.away):
            rows_by_line[float(r["line"])]=dict(r)
    except Exception as e:logger.info("Bovada FT list failed %s: %s",m.event_id,e)
    out=[]
    for line,r in rows_by_line.items():
        try:odd=float(r["odd"])
        except Exception:continue
        if line<=goals or odd<1.05 or odd>8.0:continue
        conf=unified_bot._model_confidence(p.score,p.momentum,line,goals,"FULL_TIME",m.minute,odd)
        edge=round(conf-(100/odd),1)
        needed=unified_bot._goals_needed_for_over(line,goals)
        utility=conf+edge*0.8-abs(odd-1.90)*3-max(0,needed-1)*4
        rr=dict(r,scope="FULL_TIME",confidence=conf,value_edge=edge,needed_goals=needed,whole_match_utility=utility)
        out.append(rr)
    if out:
        best=max(out,key=lambda r:(float(r.get("whole_match_utility",-999)),float(r.get("value_edge",-999)),int(r.get("confidence",0))))
        best["full_match_best"]=True
    return out

def _first_half_row(entries,m,p):
    if m.minute>45 or m.is_halftime:return None
    goals=int(m.home_score)+int(m.away_score); target=goals+.5
    try:r=get_first_half_goal_odds(m.home,m.away,m.home_score,m.away_score)
    except Exception as e:logger.info("Bovada 1H failed %s: %s",m.event_id,e); r=None
    if not r:
        for x in _ls_scope(entries,m,p,"FIRST_HALF"):
            try:
                if float(x.get("line",-99))==target:r=x; break
            except Exception:continue
    if not r:return None
    rr=dict(r); odd=float(rr["odd"]); rr.update({"scope":"FIRST_HALF","line":target,"period_goal":True,"confidence":unified_bot._model_confidence(p.score,p.momentum,target,goals,"FIRST_HALF",m.minute,odd)})
    return rr

def _target_goal_markets(entries,m,p):
    goals=int(m.home_score)+int(m.away_score); targets=(goals+.5,goals+1.5)
    ls={float(r["line"]):r for r in _ls_scope(entries,m,p,"FULL_TIME") if float(r.get("line",-99)) in targets}
    try:bov={float(r["line"]):r for r in get_goal_total_odds(m.home,m.away,m.home_score,m.away_score)}
    except Exception as e:logger.info("Bovada goal steps failed %s: %s",m.event_id,e); bov={}
    rows=[]
    for step,line in enumerate(targets,1):
        r=dict(bov.get(float(line)) or ls.get(float(line)) or {})
        if not r:continue
        odd=float(r["odd"]); conf=unified_bot._model_confidence(p.score,p.momentum,line,goals,"FULL_TIME",m.minute,odd)
        r.update({"scope":"FULL_TIME","goal_step":step,"target_label":"ещё 1 гол" if step==1 else "ещё 2 гола","confidence":conf,"value_edge":round(conf-(100/odd),1)})
        rows.append(r)
    best_all=_whole_match_candidates(entries,m,p)
    best=next((r for r in best_all if r.get("full_match_best")),None)
    if best:
        # Add separately even if its line duplicates +1/+2; flags make its role explicit.
        rows.append(best)
    first=_first_half_row(entries,m,p)
    if first:rows.append(first)
    return rows

def _market(entries,m,p):
    recs=_target_goal_markets(entries,m,p)
    goal_one=next((r for r in recs if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)
    r=goal_one or next((x for x in recs if x.get("scope")=="FULL_TIME"),None)
    if not r:return recs,{"available":False}
    odd=float(r["odd"])
    return recs,{"available":True,"scope":"FULL_TIME","line":float(r["line"]),"odd":odd,"bookmakers":r.get("bookmakers",1),"source":r.get("source",""),"goal_step":r.get("goal_step"),"market_probability":round(100/odd,1)}

def _format_strategy_signal(m,p,s,recs,goals,reason,route,master,hz,market):
    def pair(k):
        a,b=s.get(k,(0,0)); return f"{a:g}–{b:g}"
    status="Перерыв" if m.is_halftime else f"{m.minute}'"; grade=lcp._signal_grade(master)
    if reason=="goal":
        if m.minute>lcp.MAX_FOLLOWUP_MINUTE:title="✅ <b>ГОЛ — СИГНАЛ СРАБОТАЛ!</b>"; action="🏁 <b>МАТЧ ЗАКРЫТ — ДАЛЬШЕ НЕ СЧИТАЮ</b>"
        else:title="✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>\n🔄 Матч пересчитан"; action="✅ <b>ГОЛ ЗАФИКСИРОВАН</b>"
    elif reason=="followup":title="🔄 <b>ОБНОВЛЕНИЕ ПО МАТЧУ</b>"
    elif m.is_halftime:title="🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>"
    else:title="🔴 <b>LIVE-СИГНАЛ</b>"
    if reason!="goal":
        if grade=="STRONG":action="🔥 <b>МОЖНО ЗАХОДИТЬ — СИЛЬНЫЙ СИГНАЛ</b>"
        elif grade=="ENTRY":action="🟡 <b>МОЖНО РАССМАТРИВАТЬ ВХОД</b>"
        elif grade=="OBSERVE":action="👀 <b>НАБЛЮДАЮ МАТЧ — ПОКА БЕЗ ВХОДА</b>"
        else:action="⚪ <b>СИГНАЛ ОСЛАБ — НОВЫЙ ВХОД НЕ НУЖЕН</b>"
        if m.is_halftime and grade in ("ENTRY","STRONG"):action+="\n🔵 Приоритет: ещё 1 гол во 2-м тайме"
    model_goal=max(1,min(92,round(hz[3])))
    goals_now=int(m.home_score)+int(m.away_score); targets=(goals_now+.5,goals_now+1.5)
    steps={int(r.get("goal_step")):r for r in recs if r.get("scope")=="FULL_TIME" and r.get("goal_step") in (1,2)}
    price_lines=[]
    for step,line in enumerate(targets,1):
        r=steps.get(step); label="Ещё 1 гол" if step==1 else "Ещё 2 гола"
        price_lines.append(f"💰 {label}: <b>ТБ {line:g} — {float(r['odd']):.2f}</b> · {r.get('source','LIVE')}" if r else f"💰 {label}: <b>ТБ {line:g} — нет данных</b>")
    first=next((r for r in recs if r.get("period_goal") and r.get("scope")=="FIRST_HALF"),None)
    period_line=""
    if m.minute<=45 and not m.is_halftime:
        if first:period_line=f"\n⏱ <b>ГОЛ В 1-М ТАЙМЕ:</b> ТБ {float(first['line']):g} 1Т — <b>{float(first['odd']):.2f}</b> · {first.get('source','LIVE')}"
        else:period_line="\n⏱ <b>ГОЛ В 1-М ТАЙМЕ:</b> LIVE-кэф нет данных"
    best=next((r for r in recs if r.get("full_match_best")),None)
    if best:
        best_line=f"⭐ <b>ЛУЧШАЯ СТАВКА НА ВЕСЬ МАТЧ:</b> ТБ {float(best['line']):g} @ <b>{float(best['odd']):.2f}</b> · модель {int(best.get('confidence',0))}%"
    else:best_line="⭐ <b>ЛУЧШАЯ СТАВКА НА ВЕСЬ МАТЧ:</b> нет подходящего LIVE-рынка"
    stats=f"📊 xG {pair('xg')} | Удары {pair('shots')} | В створ {pair('shots_on_target')}"
    return f"{title}\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {status} | <b>{m.home_score}:{m.away_score}</b>\n\n{action}\n📈 Вероятность ещё гола: <b>{model_goal}%</b>\n"+"\n".join(price_lines)+period_line+f"\n{best_line}\n\n{stats}\n🧠 Рейтинг сигнала: <b>{master:.0f}/100</b>"

lcp._target_goal_markets=_target_goal_markets
lcp._market=_market
lcp._format_strategy_signal=_format_strategy_signal
