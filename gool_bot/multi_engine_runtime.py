"""Production runtime for GOOL auxiliary LIVE strategies.

FIRST_HALF_GOAL collects evidence from kickoff and may signal at 15'-25'.
SECOND_HALF_OVER15 decides at half-time from the complete first-half sample.
Odds are display-only and never gate an analytically eligible signal.
"""
from __future__ import annotations
import json,time,logging,requests
from pathlib import Path
import unified_bot
from live_engine import fetch_stats,fetch_summary,parse_stats,parse_goal_timeline
from signal_journal import add_signal,all_signals,update_signal
from telegram_subscribers import get_subscribers
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15,delta,first_half_goal,second_half_over15,snapshot
from multi_engine_card import render_engine_card
from robust_goal_cooldown_patch import active as persistent_goal_cooldown
from goal_timing import context as timing_context
from risk_controller import can_open
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
 return {"market":"TOTAL_OVER","scope":"FIRST_HALF" if engine==FIRST_HALF_GOAL else "SECOND_HALF","line":line,"odd":odd,"source":str(market.get("source") or "Flashscore/LSApp"),"primary_source":"Flashscore/LSApp","bookmakers":int(market.get("source_count",1) or 1),"confidence":conf,"value_edge":round(conf-(100.0/odd),1),"market_status":str(market.get("market_status") or "PRIMARY_ONLY"),"steam_score":0.0,"source_prices":market.get("source_prices") or []}
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
 row={"journal_version":6,"kind":"live","engine":engine,"event_id":match.event_id,"home":match.home,"away":match.away,"league":match.league,"minute":match.minute,"score_at_signal":f"{match.home_score}:{match.away_score}","strategy_score":score,"trend_delta":d,"reason":reason,"result":"pending","stake_units":1.0}
 if primary:
  row.update({"odd":primary["odd"],"primary":primary,"market_status":primary["market_status"]})
 else:
  row.update({"odd":None,"primary":None,"market_status":"NO_PRICE","odds_display_only":True})
 return add_signal(row,_journal_key(engine,match.event_id))
def _active_rows():return [r for r in all_signals() if r.get("engine") in {FIRST_HALF_GOAL,SECOND_HALF_OVER15} and str(r.get("result") or "pending").strip().lower()=="pending"]
def _score_at_signal(row):
 try:a,b=map(int,str(row.get("score_at_signal","0:0")).split(":"));return a,b
 except:return 0,0
def _result_delta(row):
 d=dict(row.get("trend_delta") or {});p=row.get("primary") or {};d["_market"]={"line":p.get("line"),"odd":p.get("odd"),"market_status":p.get("market_status") or "NO_PRICE","source_prices":p.get("source_prices") or []};return d
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
def _fh_market(m):return best_consensus(first_half_next_total(m.event_id,m.home,m.away,int(m.home_score)+int(m.away_score)))
def _ht_market(m):return best_consensus(second_half_market(m.event_id,m.home,m.away))
def scan_engines(live):
 state=_load();live_by={str(m.event_id):m for m in live};now=time.time();_settle_active(live_by);journal=all_signals();c={"live":len(live),"fh_seen":0,"fh_eligible":0,"ht_seen":0,"ht_eligible":0,"duplicate":0,"exposure":0,"priced":0,"unpriced":0,"sent":0}
 for m in live:
  minute=int(getattr(m,"minute",0) or 0);is_ht=bool(getattr(m,"is_halftime",False))
  if 0<=minute<=25 and not is_ht:
   c["fh_seen"]+=1;body=fetch_stats(m.event_id)
   if not body:continue
   stats=parse_stats(body)
   if not stats:continue
   key=f"fhtrend:{m.event_id}";s=state.setdefault(key,{"ts":now,"snaps":[]});snaps=s.setdefault("snaps",[]);snap={"minute":minute,"stats":snapshot(stats)}
   if not snaps or int(snaps[-1].get("minute",-1))!=minute:snaps.append(snap)
   s["snaps"]=snaps[-30:];s["ts"]=now
   if minute<15:continue
   baseline=s["snaps"][0].get("stats") if s["snaps"] else {};d=delta(stats,baseline);goals=parse_goal_timeline(fetch_summary(m.event_id));last=_last_goal(goals)
   if persistent_goal_cooldown(m.event_id,minute):last=minute
   timing=timing_context(m,FIRST_HALF_GOAL);d["_timing"]=timing;dec=first_half_goal(minute,d,last,timing.get("bonus",0))
   if not dec.eligible:continue
   c["fh_eligible"]+=1;engine=FIRST_HALF_GOAL;market=_fh_market(m)
  elif is_ht:
   c["ht_seen"]+=1;engine=SECOND_HALF_OVER15
   if any(r.get("engine")==engine and str(r.get("event_id"))==str(m.event_id) for r in journal):c["duplicate"]+=1;continue
   body=fetch_stats(m.event_id)
   if not body:continue
   stats=parse_stats(body)
   if not stats:continue
   timing=timing_context(m,SECOND_HALF_OVER15);dec=second_half_over15(stats,timing.get("bonus",0));d=snapshot(stats);d["_timing"]=timing
   if not dec.eligible:continue
   c["ht_eligible"]+=1;market=_ht_market(m)
  else:continue
  if any(r.get("engine")==engine and str(r.get("event_id"))==str(m.event_id) for r in journal):c["duplicate"]+=1;continue
  allowed,why=can_open(journal,m.event_id)
  if not allowed:c["exposure"]+=1;logger.info("ENGINE_EXPOSURE_REJECT %s %s %s",engine,m.event_id,why);continue
  odd=float(market.get("odd",0) or 0) if market else None
  if market:
   c["priced"]+=1;d["_market"]={"line":market.get("line"),"odd":market.get("odd"),"market_status":market.get("market_status"),"source_count":market.get("source_count"),"source_prices":market.get("source_prices") or []}
  else:
   c["unpriced"]+=1;d["_market"]={"line":None,"odd":None,"market_status":"NO_PRICE","source_count":0,"source_prices":[]}
  if _record(m,engine,dec.score,d,market) and _send_all(m,engine,dec.score,d,odd):c["sent"]+=1;journal=all_signals()
 _save(state);logger.info("ENGINE_SCAN_DIAG %s",c)
