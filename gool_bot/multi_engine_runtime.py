"""Production runtime for one-shot GOOL HT HUNTER and LATE RISK engines."""
from __future__ import annotations
import json,time,logging,requests
from pathlib import Path
import unified_bot
from live_engine import fetch_stats,fetch_summary,parse_stats,parse_goal_timeline,calculate_goal_pressure,get_previous_values
from live_odds import fetch_live_odds
from signal_journal import add_signal,all_signals,update_signal
from telegram_subscribers import get_subscribers
from multi_engine import HT_HUNTER,LATE_RISK,delta,ht_hunter,late_risk,snapshot
from multi_engine_card import render_engine_card
from robust_goal_cooldown_patch import active as persistent_goal_cooldown
from goal_timing import context as timing_context
from risk_controller import can_open,value_ok
logger=logging.getLogger("multi_engine_runtime")
STATE_FILE=Path("multi_engine_state.json");GOAL_CONFIRM_SECONDS=35

def _load():
    try:d=json.loads(STATE_FILE.read_text("utf-8"));return d if isinstance(d,dict) else {}
    except:return {}
def _save(d):
    cutoff=time.time()-10*3600;d={k:v for k,v in d.items() if isinstance(v,dict) and float(v.get("ts",0) or 0)>=cutoff};STATE_FILE.write_text(json.dumps(d,ensure_ascii=False),"utf-8")
def _last_goal(goal_times):
    vals=[]
    for x in goal_times or []:
        try:vals.append(int(str(x).split("'",1)[0].split("+",1)[0]))
        except:pass
    return max(vals) if vals else None

def _pair(stats,key):
    try:a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
    except:return 0.0,0.0

def _late_context(match,stats):
    """Require a plausible chasing scenario; red cards modify, never create, a setup."""
    diff=abs(int(match.home_score)-int(match.away_score));reds=_pair(stats,"red_cards")
    if diff==0:return True,{"state":"draw","score_diff":0,"red_cards":reds,"chase":None}
    trailing=0 if int(match.home_score)<int(match.away_score) else 1;leading=1-trailing
    xg=_pair(stats,"xg")[trailing];sot=_pair(stats,"shots_on_target")[trailing];inside=_pair(stats,"shots_inside_box")[trailing];touches=_pair(stats,"touches_box")[trailing];corners=_pair(stats,"corners")[trailing]
    chase=min(100.0,xg*22+sot*10+inside*3+touches*.8+corners*2)
    threshold=28.0 if diff==1 else 48.0
    red_delta=reds[leading]-reds[trailing]
    if red_delta>0:threshold=max(18.0,threshold-10.0)
    elif red_delta<0:threshold+=15.0
    ok=chase>=threshold
    return ok,{"state":"one_goal" if diff==1 else "two_plus","score_diff":diff,"trailing_side":"home" if trailing==0 else "away","chase":round(chase,1),"threshold":round(threshold,1),"red_cards":reds}

def _market(match,pressure,engine):
    try:recs=unified_bot._recommendations(fetch_live_odds(match.event_id),match,pressure)
    except Exception:return None
    scope="FIRST_HALF" if engine==HT_HUNTER else "FULL_TIME";goals=int(match.home_score)+int(match.away_score);rows=[]
    for r in recs:
        try:o=float(r.get("odd",0));line=float(r.get("line",0))
        except:continue
        if r.get("scope")==scope and 1.15<=o<=5.0 and line>goals:rows.append(r)
    if not rows:return None
    return max(rows,key=lambda r:(float(r.get("value_edge",-999) or -999),-abs(float(r.get("odd",0))-2.0)))

def _primary(engine,market):
    if not market:return None
    try:odd=float(market["odd"]);conf=float(market.get("confidence"))
    except (KeyError,TypeError,ValueError):return None
    edge=market.get("value_edge")
    try:edge=float(edge)
    except (TypeError,ValueError):edge=round(conf-(100.0/odd),1)
    mv=market.get("market_movement") or {}
    return {"market":"TOTAL_OVER","scope":"FIRST_HALF" if engine==HT_HUNTER else "FULL_TIME","line":float(market["line"]),"odd":odd,"source":str(market.get("source") or "LIVE"),"bookmakers":int(market.get("bookmakers",0) or 0),"confidence":conf,"value_edge":edge,"market_status":str(market.get("market_status") or mv.get("status") or "EARLY"),"steam_score":float(market.get("steam_score",mv.get("steam_score",0)) or 0),"market_movement":mv}

def _send_all(match,engine,score,d,odd,result=None):
    token=unified_bot.BOT_TOKEN;subs=get_subscribers()
    if not token or not subs:return False
    try:png=render_engine_card(match,engine,score,d,odd,result)
    except Exception as e:logger.exception("ENGINE_CARD_FAILED %s",e);png=None
    if result=="win":caption="✅ GOOL AI • ЗАХОД! • "+("ПЕРВЫЙ ТАЙМ" if engine==HT_HUNTER else "ВТОРОЙ ТАЙМ")
    elif result=="loss":caption="❌ GOOL AI • НЕ ЗАШЁЛ • "+("ПЕРВЫЙ ТАЙМ" if engine==HT_HUNTER else "ВТОРОЙ ТАЙМ")
    else:caption=("🔵 GOOL AI • HT HUNTER • ПЕРВЫЙ ТАЙМ" if engine==HT_HUNTER else "🔴 GOOL AI • LATE RISK • ВТОРОЙ ТАЙМ")
    ok=0
    for cid in subs:
        try:
            if png:r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":caption},files={"photo":("gool-engine.png",png,"image/png")},timeout=25)
            else:r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":str(cid),"text":caption},timeout=15)
            ok+=int(r.ok)
        except requests.RequestException:pass
    logger.info("ENGINE_DELIVERED %s %s %d/%d",engine,result or "signal",ok,len(subs));return ok>0

def _journal_key(engine,eid):return f"engine:{engine}:{eid}"
def _record(match,engine,score,d,market):
    primary=_primary(engine,market);reason="ht_hunter" if engine==HT_HUNTER else "late_risk"
    if not primary:return False
    ok,why=value_ok(primary,reason)
    if not ok:logger.info("ENGINE_VALUE_REJECT %s %s %s",engine,match.event_id,why);return False
    return add_signal({"journal_version":4,"kind":"live","engine":engine,"event_id":match.event_id,"home":match.home,"away":match.away,"league":match.league,"minute":match.minute,"score_at_signal":f"{match.home_score}:{match.away_score}","risk_score":score,"trend_delta":d,"odd":primary["odd"],"primary":primary,"market_status":primary["market_status"],"steam_score":primary["steam_score"],"reason":reason,"result":"pending","stake_units":1.0,"next_goal_hit":False},_journal_key(engine,match.event_id))
def _active_rows():return [r for r in all_signals() if r.get("engine") in {HT_HUNTER,LATE_RISK} and str(r.get("result") or "pending").strip().lower()=="pending"]

def scan_engines(live):
    state=_load();live_by={str(m.event_id):m for m in live};now=time.time();counters={"live":len(live),"window":0,"stats":0,"baseline":0,"eligible":0,"scenario_reject":0,"duplicate":0,"exposure":0,"market":0,"value_reject":0,"no_market":0,"sent":0}
    for row in _active_rows():
        eid=str(row.get("event_id"));m=live_by.get(eid);engine=row.get("engine");ek=f"active:{engine}:{eid}";st=state.setdefault(ek,{"ts":now})
        try:sh,sa=map(int,str(row.get("score_at_signal","0:0")).split(":"))
        except:sh=sa=0
        if m and int(m.home_score)+int(m.away_score)>sh+sa:
            current=f"{m.home_score}:{m.away_score}"
            if st.get("goal_score")!=current:st.update(goal_score=current,goal_seen_ts=now,ts=now);continue
            if now-float(st.get("goal_seen_ts",now))>=GOAL_CONFIRM_SECONDS:
                update_signal(str(row.get("dedupe_key") or ""),next_goal_hit=True,next_goal_score=current,next_goal_minute=int(m.minute),next_goal_confirmed_ts=int(now));st.update(goal_confirmed=True,ts=now)
            continue
        st["ts"]=now
    journal=all_signals()
    for m in live:
        minute=int(getattr(m,"minute",0) or 0)
        if not (25<=minute<=38 or 70<=minute<=85):continue
        counters["window"]+=1;body=fetch_stats(m.event_id)
        if not body:continue
        stats=parse_stats(body)
        if not stats:continue
        counters["stats"]+=1;key=f"trend:{m.event_id}";s=state.setdefault(key,{"ts":now,"snaps":[]});snaps=s.setdefault("snaps",[]);snap={"minute":minute,"stats":snapshot(stats)}
        if not snaps or int(snaps[-1].get("minute",-1))!=minute:snaps.append(snap)
        s["snaps"]=[x for x in snaps if minute-int(x.get("minute",minute))<=20][-24:];old=[x for x in s["snaps"] if int(x.get("minute",0))<=minute-10];s["ts"]=now
        if not old:continue
        counters["baseline"]+=1;d=delta(stats,old[-1].get("stats"));goals=parse_goal_timeline(fetch_summary(m.event_id));last=_last_goal(goals)
        if persistent_goal_cooldown(m.event_id,minute):last=minute
        prev=get_previous_values(m.event_id,minute,8);pressure=calculate_goal_pressure(m,stats,prev);engines=[]
        if 35<=minute<=38:
            timing=timing_context(m,HT_HUNTER);dht=dict(d);dht["_timing"]=timing;engines.append((HT_HUNTER,ht_hunter(minute,d,last,timing.get("bonus",0)),dht))
        if 80<=minute<=85:
            timing=timing_context(m,LATE_RISK);dlr=dict(d);dlr["_timing"]=timing;engines.append((LATE_RISK,late_risk(minute,d,last,timing.get("bonus",0)),dlr))
        for engine,dec,card_delta in engines:
            if not dec.eligible:continue
            counters["eligible"]+=1
            if engine==LATE_RISK:
                scenario_ok,ctx=_late_context(m,stats);card_delta["_game_state"]=ctx
                if not scenario_ok:counters["scenario_reject"]+=1;logger.info("LATE_SCENARIO_REJECT %s %s",m.event_id,ctx);continue
            if any(r.get("engine")==engine and str(r.get("event_id"))==str(m.event_id) for r in journal):counters["duplicate"]+=1;continue
            allowed,why=can_open(journal,m.event_id)
            if not allowed:counters["exposure"]+=1;logger.info("ENGINE_EXPOSURE_REJECT %s %s %s",engine,m.event_id,why);continue
            market=_market(m,pressure,engine)
            if not market:counters["no_market"]+=1;continue
            primary=_primary(engine,market);ok,why=value_ok(primary,"ht_hunter" if engine==HT_HUNTER else "late_risk")
            if not ok:counters["value_reject"]+=1;logger.info("ENGINE_VALUE_REJECT %s %s %s",engine,m.event_id,why);continue
            counters["market"]+=1;odd=float(market.get("odd",0) or 0)
            if _record(m,engine,dec.score,card_delta,market) and _send_all(m,engine,dec.score,card_delta,odd):counters["sent"]+=1;journal=all_signals()
    _save(state);logger.info("ENGINE_SCAN_DIAG %s",counters)
