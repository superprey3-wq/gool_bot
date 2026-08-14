"""Production runtime for one-shot GOOL HT HUNTER and LATE RISK engines."""
from __future__ import annotations
import json,time,logging,requests
from pathlib import Path
import unified_bot
from live_engine import fetch_stats,fetch_summary,parse_stats,parse_goal_timeline,calculate_goal_pressure,get_previous_values
from prematch_scanner import _fetch_event_odds
from signal_journal import add_signal,all_signals,update_signal
from telegram_subscribers import get_subscribers
from multi_engine import HT_HUNTER,LATE_RISK,delta,ht_hunter,late_risk,snapshot
from multi_engine_card import render_engine_card
logger=logging.getLogger("multi_engine_runtime")
STATE_FILE=Path("multi_engine_state.json")
GOAL_CONFIRM_SECONDS=35

def _load():
    try:
        d=json.loads(STATE_FILE.read_text("utf-8"));return d if isinstance(d,dict) else {}
    except:return {}
def _save(d):
    cutoff=time.time()-10*3600;d={k:v for k,v in d.items() if isinstance(v,dict) and float(v.get("ts",0) or 0)>=cutoff};STATE_FILE.write_text(json.dumps(d,ensure_ascii=False),"utf-8")
def _last_goal(goal_times):
    vals=[]
    for x in goal_times or []:
        try:vals.append(int(str(x).split("'",1)[0].split("+",1)[0]))
        except:pass
    return max(vals) if vals else None
def _market(match,pressure,engine):
    try:recs=unified_bot._recommendations(_fetch_event_odds(match.event_id),match,pressure)
    except Exception:return None
    scope="FIRST_HALF" if engine==HT_HUNTER else "FULL_TIME";goals=int(match.home_score)+int(match.away_score);rows=[]
    for r in recs:
        try:o=float(r.get("odd",0));line=float(r.get("line",0))
        except:continue
        if r.get("scope")==scope and 1.15<=o<=5.0 and line>goals:rows.append(r)
    return min(rows,key=lambda r:abs(float(r.get("odd",0))-2.2)) if rows else None
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
def _record(match,engine,score,d,odd):
    key=_journal_key(engine,match.event_id);return add_signal({"kind":"live","engine":engine,"event_id":match.event_id,"home":match.home,"away":match.away,"league":match.league,"minute":match.minute,"score_at_signal":f"{match.home_score}:{match.away_score}","risk_score":score,"trend_delta":d,"odd":odd,"reason":"ht_hunter" if engine==HT_HUNTER else "late_risk","result":"pending"},key)
def _settle(engine,eid,result,match=None):
    fields={"result":"+" if result=="win" else "-","settled_ts":int(time.time())}
    if match:fields.update(final_score=f"{match.home_score}:{match.away_score}",goal_minute=int(match.minute))
    return update_signal(_journal_key(engine,eid),**fields)
def _active_rows():return [r for r in all_signals() if r.get("engine") in {HT_HUNTER,LATE_RISK} and str(r.get("result") or "pending")=="pending"]

def scan_engines(live):
    state=_load();live_by={str(m.event_id):m for m in live};now=time.time()
    for row in _active_rows():
        eid=str(row.get("event_id"));engine=row.get("engine");m=live_by.get(eid);ek=f"active:{engine}:{eid}";st=state.setdefault(ek,{"ts":now})
        try:sh,sa=map(int,str(row.get("score_at_signal","0:0")).split(":"))
        except:sh=sa=0
        if m and int(m.home_score)+int(m.away_score)>sh+sa:
            current=f"{m.home_score}:{m.away_score}"
            if st.get("goal_score")!=current:st.update(goal_score=current,goal_seen_ts=now,ts=now);continue
            if now-float(st.get("goal_seen_ts",now))>=GOAL_CONFIRM_SECONDS:
                _settle(engine,eid,"win",m);_send_all(m,engine,float(row.get("risk_score",0)),row.get("trend_delta") or {},row.get("odd"),"win");st.update(settled=True,ts=now)
            continue
        st.pop("goal_score",None);st.pop("goal_seen_ts",None);st["ts"]=now
        if engine==HT_HUNTER and m and (getattr(m,"is_halftime",False) or int(m.minute)>45):
            _settle(engine,eid,"loss",m);_send_all(m,engine,float(row.get("risk_score",0)),row.get("trend_delta") or {},row.get("odd"),"loss");st["settled"]=True
        elif not m and now-float(row.get("created_ts",0) or 0)>10*60:_settle(engine,eid,"loss",None);st["settled"]=True
    journal=all_signals()
    for m in live:
        minute=int(getattr(m,"minute",0) or 0)
        if not (25<=minute<=45 or 70<=minute<=90):continue
        body=fetch_stats(m.event_id)
        if not body:continue
        stats=parse_stats(body)
        if not stats:continue
        key=f"trend:{m.event_id}";s=state.setdefault(key,{"ts":now,"snaps":[]});snaps=s.setdefault("snaps",[]);snap={"minute":minute,"stats":snapshot(stats)}
        if not snaps or int(snaps[-1].get("minute",-1))!=minute:snaps.append(snap)
        s["snaps"]=[x for x in snaps if minute-int(x.get("minute",minute))<=20][-24:];old=[x for x in s["snaps"] if int(x.get("minute",0))<=minute-10]
        s["ts"]=now
        if not old:continue
        d=delta(stats,old[-1].get("stats"));goals=parse_goal_timeline(fetch_summary(m.event_id));last=_last_goal(goals);prev=get_previous_values(m.event_id,minute,8);pressure=calculate_goal_pressure(m,stats,prev);engines=[]
        if 35<=minute<=45:engines.append((HT_HUNTER,ht_hunter(minute,d,last)))
        if 80<=minute<=90:engines.append((LATE_RISK,late_risk(minute,d,last)))
        for engine,dec in engines:
            if not dec.eligible:continue
            if any(r.get("engine")==engine and str(r.get("event_id"))==str(m.event_id) for r in journal):continue
            market=_market(m,pressure,engine)
            if not market:continue
            odd=float(market.get("odd",0) or 0)
            if _record(m,engine,dec.score,d,odd) and _send_all(m,engine,dec.score,d,odd):
                logger.info("ENGINE_SIGNAL %s %s - %s minute=%d score=%.1f odd=%.2f",engine,m.home,m.away,minute,dec.score,odd);journal=all_signals()
    _save(state)
