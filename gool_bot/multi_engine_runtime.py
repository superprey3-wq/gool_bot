"""Production runtime for GOOL auxiliary LIVE strategies.

FIRST_HALF_GOAL collects evidence from kickoff and may signal at 15'-25'.
SECOND_HALF_OVER15 decides at half-time from the complete first-half sample.
"""
from __future__ import annotations
import json,time,logging,requests
from collections import Counter
from pathlib import Path
import unified_bot
from live_engine import fetch_stats,fetch_summary,parse_stats,parse_goal_timeline
from signal_journal import add_signal,all_signals,update_signal
from telegram_subscribers import get_subscribers
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15,delta,first_half_goal,second_half_over15,snapshot
from multi_engine_card import render_engine_card
from robust_goal_cooldown_patch import active as persistent_goal_cooldown
from goal_timing import context as timing_context
from risk_controller import can_open,value_ok
from aux_strategy_markets import first_half_next_total,second_half_over15 as second_half_market,best_consensus
logger=logging.getLogger("multi_engine_runtime");STATE_FILE=Path("multi_engine_state.json")
def _load():
 try:d=json.loads(STATE_FILE.read_text("utf-8"));return d if isinstance(d,dict) else {}
 except:return {}
def _save(d):
 cutoff=time.time()-10*3600;d={k:v for k,v in d.items() if isinstance(v,dict) and float(v.get("ts",0) or 0)>=cutoff};STATE_FILE.write_text(json.dumps(d,ensure_ascii=False),"utf-8")
def _last_goal(xs):
 vals=[]
 for x in xs or []:
  try:vals.append(int(str(x).split("'",1)[0].split("+",1)[0]))
  except:pass
 return max(vals) if vals else None
def _primary(engine,market,confidence):
 if not market:return None
 try:odd=float(market["odd"]);line=float(market["line"]);conf=float(confidence)
 except (KeyError,TypeError,ValueError):return None
 return {"market":"TOTAL_OVER","scope":"FIRST_HALF" if engine==FIRST_HALF_GOAL else "SECOND_HALF","line":line,"odd":odd,"source":str(market.get("source") or "LIVE"),"bookmakers":int(market.get("source_count",1) or 1),"confidence":conf,"value_edge":round(conf-(100.0/odd),1),"market_status":str(market.get("market_status") or "EARLY"),"steam_score":0.0,"source_prices":market.get("source_prices") or []}
def _send_all(match,engine,score,d,odd,result=None):
 token=unified_bot.BOT_TOKEN;subs=get_subscribers()
 if not token or not subs:return False
 try:png=render_engine_card(match,engine,score,d,odd,result)
 except Exception as e:logger.exception("ENGINE_CARD_FAILED %s",e);png=None
 label="ГОЛ В 1-М ТАЙМЕ" if engine==FIRST_HALF_GOAL else "ТБ1.5 ВО 2-М ТАЙМЕ";caption=(f"✅ GOOL AI • ЗАШЛО • {label}" if result=="win" else f"❌ GOOL AI • НЕ ЗАШЛО • {label}" if result=="loss" else f"🎯 GOOL AI • {label}");ok=0
 for cid in subs:
  try:
   if png:r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":caption},files={"photo":("gool-engine.png",png,"image/png")},timeout=25)
   else:r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":str(cid),"text":caption},timeout=15)
   ok+=int(r.ok)
  except requests.RequestException:pass
 logger.info("ENGINE_DELIVERED %s %s %d/%d",engine,result or "signal",ok,len(subs));return ok>0
def _journal_key(engine,eid):return f"engine:{engine}:{eid}"
def _record(match,engine,score,d,market):
 primary=_primary(engine,market,score);reason="first_half_goal" if engine==FIRST_HALF_GOAL else "second_half_over15"
 if not primary:return False
 ok,why=value_ok(primary,reason)
 if not ok:logger.info("ENGINE_VALUE_REJECT %s %s %s",engine,match.event_id,why);return False
 return add_signal({"journal_version":5,"kind":"live","engine":engine,"event_id":match.event_id,"home":match.home,"away":match.away,"league":match.league,"minute":match.minute,"score_at_signal":f"{match.home_score}:{match.away_score}","strategy_score":score,"trend_delta":d,"odd":primary["odd"],"primary":primary,"market_status":primary["market_status"],"reason":reason,"result":"pending","stake_units":1.0},_journal_key(engine,match.event_id))
def _active_rows():return [r for r in all_signals() if r.get("engine") in {FIRST_HALF_GOAL,SECOND_HALF_OVER15} and str(r.get("result") or "pending").strip().lower()=="pending"]
def _score_at_signal(row):
 try:a,b=map(int,str(row.get("score_at_signal","0:0")).split(":"));return a,b
 except:return 0,0
def _result_delta(row):
 d=dict(row.get("trend_delta") or {});p=row.get("primary") or {};d["_market"]={"line":p.get("line"),"odd":p.get("odd"),"market_status":p.get("market_status"),"source_prices":p.get("source_prices") or []};return d
def _settle_active(live_by):
 for row in _active_rows():
  m=live_by.get(str(row.get("event_id")))
  if not m:continue
  sh,sa=_score_at_signal(row);start=sh+sa;now_goals=int(m.home_score)+int(m.away_score);engine=row.get("engine");key=str(row.get("dedupe_key") or "");d=_result_delta(row);odd=row.get("odd")
  if engine==FIRST_HALF_GOAL:
   if now_goals>start:update_signal(key,result="win",final_score=f"{m.home_score}:{m.away_score}",result_minute=int(m.minute));_send_all(m,engine,float(row.get("strategy_score",0) or 0),d,odd,"win")
   elif bool(getattr(m,"is_halftime",False)) or int(getattr(m,"minute",0) or 0)>=46:update_signal(key,result="loss",final_score=f"{m.home_score}:{m.away_score}",result_minute=int(m.minute));_send_all(m,engine,float(row.get("strategy_score",0) or 0),d,odd,"loss")
  elif engine==SECOND_HALF_OVER15:
   if now_goals-start>=2:update_signal(key,result="win",final_score=f"{m.home_score}:{m.away_score}",result_minute=int(m.minute));_send_all(m,engine,float(row.get("strategy_score",0) or 0),d,odd,"win")
   elif int(getattr(m,"minute",0) or 0)>=90:update_signal(key,result="loss",final_score=f"{m.home_score}:{m.away_score}",result_minute=int(m.minute));_send_all(m,engine,float(row.get("strategy_score",0) or 0),d,odd,"loss")
def _fh_market(m):return best_consensus(first_half_next_total(m.home,m.away,int(m.home_score)+int(m.away_score)))
def _ht_market(m):return best_consensus(second_half_market(m.home,m.away))
def _evidence_fh(d):return sum((d.get("xg",0)>=.18,d.get("xgot",0)>=.15,d.get("shots",0)>=2,d.get("shots_on_target",0)>=1,d.get("big_chances",0)>=1,d.get("touches_box",0)>=5))
def _evidence_ht(stats):
 def t(k):
  try:a,b=stats.get(k,(0,0));return float(a)+float(b)
  except:return 0.0
 return sum((t("xg")>=1.15,t("xgot")>=.85,t("shots")>=12,t("shots_on_target")>=4,t("big_chances")>=2,t("shots_inside_box")>=6,t("touches_box")>=20,t("corners")>=4))
def _reject(counter,code,m,engine,dec=None,detail="",near=False):
 counter[code]+=1;logger.info("ENGINE_REJECT engine=%s match=%s-%s event=%s minute=%s score=%s:%s code=%s strategy_score=%s near_miss=%s %s",engine,m.home,m.away,m.event_id,getattr(m,"minute",0),m.home_score,m.away_score,code,getattr(dec,"score",None),int(bool(near)),detail)
def scan_engines(live):
 state=_load();live_by={str(m.event_id):m for m in live};now=time.time();_settle_active(live_by);journal=all_signals();c={"live":len(live),"fh_seen":0,"fh_eligible":0,"ht_seen":0,"ht_eligible":0,"duplicate":0,"exposure":0,"market":0,"value_reject":0,"sent":0};rejects=Counter()
 for m in live:
  minute=int(getattr(m,"minute",0) or 0);is_ht=bool(getattr(m,"is_halftime",False))
  if 0<=minute<=25 and not is_ht:
   c["fh_seen"]+=1;body=fetch_stats(m.event_id)
   if not body:_reject(rejects,"NO_STATS_BODY",m,FIRST_HALF_GOAL);continue
   stats=parse_stats(body)
   if not stats:_reject(rejects,"NO_PARSED_STATS",m,FIRST_HALF_GOAL);continue
   key=f"fhtrend:{m.event_id}";s=state.setdefault(key,{"ts":now,"snaps":[]});snaps=s.setdefault("snaps",[]);snap={"minute":minute,"stats":snapshot(stats)}
   if not snaps or int(snaps[-1].get("minute",-1))!=minute:snaps.append(snap)
   s["snaps"]=snaps[-30:];s["ts"]=now
   if minute<15:_reject(rejects,"COLLECTING",m,FIRST_HALF_GOAL,detail="signal_window=15-25");continue
   baseline=s["snaps"][0].get("stats") if s["snaps"] else {};d=delta(stats,baseline);goals=parse_goal_timeline(fetch_summary(m.event_id));last=_last_goal(goals)
   if persistent_goal_cooldown(m.event_id,minute):last=minute
   timing=timing_context(m,FIRST_HALF_GOAL);d["_timing"]=timing;dec=first_half_goal(minute,d,last,timing.get("bonus",0))
   if not dec.eligible:
    ev=_evidence_fh(d);needed=3 if minute>=22 else 2;near=(dec.score>=59 and ev>=max(1,needed-1));code="POST_GOAL_COOLDOWN" if "cooldown" in dec.reason else "LOW_SCORE" if dec.score<64 and ev>=needed else "LOW_EVIDENCE" if ev<needed and dec.score>=64 else "LOW_SCORE_AND_EVIDENCE"
    _reject(rejects,code,m,FIRST_HALF_GOAL,dec,f"required_score=64 evidence={ev}/{needed} xg={d.get('xg',0):.2f} xgot={d.get('xgot',0):.2f} shots={d.get('shots',0):.0f} sot={d.get('shots_on_target',0):.0f} big={d.get('big_chances',0):.0f} box_touches={d.get('touches_box',0):.0f}; {dec.reason}",near);continue
   c["fh_eligible"]+=1;engine=FIRST_HALF_GOAL;market=_fh_market(m)
  elif is_ht:
   c["ht_seen"]+=1;engine=SECOND_HALF_OVER15
   if any(r.get("engine")==engine and str(r.get("event_id"))==str(m.event_id) for r in journal):c["duplicate"]+=1;_reject(rejects,"DUPLICATE",m,engine);continue
   body=fetch_stats(m.event_id)
   if not body:_reject(rejects,"NO_STATS_BODY",m,engine);continue
   stats=parse_stats(body)
   if not stats:_reject(rejects,"NO_PARSED_STATS",m,engine);continue
   timing=timing_context(m,SECOND_HALF_OVER15);dec=second_half_over15(stats,timing.get("bonus",0));d=snapshot(stats);d["_timing"]=timing
   if not dec.eligible:
    ev=_evidence_ht(stats);near=(dec.score>=65 and ev>=3);code="LOW_SCORE" if dec.score<70 and ev>=4 else "LOW_EVIDENCE" if ev<4 and dec.score>=70 else "LOW_SCORE_AND_EVIDENCE"
    _reject(rejects,code,m,engine,dec,f"required_score=70 evidence={ev}/4; {dec.reason}",near);continue
   c["ht_eligible"]+=1;market=_ht_market(m)
  else:continue
  if any(r.get("engine")==engine and str(r.get("event_id"))==str(m.event_id) for r in journal):c["duplicate"]+=1;_reject(rejects,"DUPLICATE",m,engine,dec);continue
  allowed,why=can_open(journal,m.event_id)
  if not allowed:c["exposure"]+=1;_reject(rejects,"EXPOSURE",m,engine,dec,str(why));continue
  if not market:_reject(rejects,"NO_MARKET",m,engine,dec);continue
  primary=_primary(engine,market,dec.score);reason="first_half_goal" if engine==FIRST_HALF_GOAL else "second_half_over15";ok,why=value_ok(primary,reason)
  if not ok:c["value_reject"]+=1;_reject(rejects,"VALUE",m,engine,dec,str(why),near=True);continue
  c["market"]+=1;odd=float(market.get("odd",0) or 0);d["_market"]={"line":market.get("line"),"odd":market.get("odd"),"market_status":market.get("market_status"),"source_count":market.get("source_count"),"source_prices":market.get("source_prices") or []}
  if _record(m,engine,dec.score,d,market) and _send_all(m,engine,dec.score,d,odd):c["sent"]+=1;journal=all_signals()
 _save(state);logger.info("ENGINE_SCAN_DIAG %s rejects=%s",c,dict(rejects))
