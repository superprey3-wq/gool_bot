"""Fast single-pass GOOL CORE runtime.

Goals:
- analyse the already-discovered LIVE list once per server cycle;
- never fetch summary/history/odds for every match;
- fetch basic stats concurrently;
- one active CORE entry per event until FAST GOAL WATCH settles it;
- keep the approved CORE scoring/evaluation and cards.
"""
from __future__ import annotations
import logging,time
from concurrent.futures import ThreadPoolExecutor,as_completed
import live_candidate_patch as lc
import unified_bot
from live_engine import StatsSnapshot,calculate_goal_pressure,fetch_stats,fetch_summary,get_previous_values,parse_goal_timeline,parse_stats,save_snapshot
logger=logging.getLogger("fast_core_runtime");MAX_STATS_WORKERS=12;CHEAP_PREFILTER=45.0

def _core_minute_ok(m):
 minute=int(getattr(m,"minute",0) or 0)
 if bool(getattr(m,"is_halftime",False)):return False
 if minute<10:return False
 if 46<=minute<55:return False
 return minute<=lc.MAX_NEW_SIGNAL_MINUTE

def _fetch_one(m):
 try:
  body=fetch_stats(m.event_id);return m,parse_stats(body) if body else {}
 except Exception as exc:logger.info("FAST_CORE_STATS_FAILED %s: %s",getattr(m,"event_id","?"),exc);return m,{}
def _candidate_summary(m):
 try:
  body=fetch_summary(m.event_id);return parse_goal_timeline(body) if body else []
 except Exception as exc:logger.info("FAST_CORE_SUMMARY_FAILED %s: %s",getattr(m,"event_id","?"),exc);return []
async def scan_live_once_fast():
 live=await unified_bot.discover_live_matches();state=unified_bot._load_sent();sent=0;ids={str(m.event_id) for m in live}
 for key in list(state):
  if str(key).startswith("TRACK:") and str(key).split(":",1)[1] not in ids:state.pop(key,None)
 pending=[m for m in live if _core_minute_ok(m) and f"TRACK:{m.event_id}" not in state]
 logger.info("FAST_CORE cycle live=%d candidates_by_time=%d tracked=%d",len(live),len(pending),sum(1 for k in state if str(k).startswith("TRACK:")))
 stats_by_id={}
 if pending:
  with ThreadPoolExecutor(max_workers=min(MAX_STATS_WORKERS,len(pending))) as pool:
   futures=[pool.submit(_fetch_one,m) for m in pending]
   for fut in as_completed(futures):
    m,stats=fut.result();stats_by_id[str(m.event_id)]=stats
 shortlisted=evaluated=0
 for m in pending:
  s=stats_by_id.get(str(m.event_id)) or {}
  if not s:continue
  prev=get_previous_values(m.event_id,m.minute,8);p=calculate_goal_pressure(m,s,prev)
  try:save_snapshot(m.event_id,StatsSnapshot(int(time.time()),m.minute,s))
  except Exception as exc:logger.info("FAST_CORE_SNAPSHOT_FAILED %s: %s",m.event_id,exc)
  cheap=max(float(p.score),float(lc._dom(m,s)),float(lc._threat(s)),float(lc._under(m,s)))
  if cheap<CHEAP_PREFILTER:continue
  shortlisted+=1;goals=_candidate_summary(m);recs=[];market={"available":False};qualifies,route,master,sc,hz,market=lc._evaluate(m,s,p,goals,market);evaluated+=1;grade=lc._signal_grade(master)
  logger.info("FAST_CORE_EVAL %d' %s — %s %d:%d cheap=%.0f master=%.0f grade=%s %s",m.minute,m.home,m.away,m.home_score,m.away_score,cheap,master,grade,"PASS" if qualifies else "REJECT")
  if not qualifies or grade not in {"ENTRY","STRONG"}:continue
  try:entries=unified_bot._fetch_event_odds(m.event_id);recs,market=lc._market(entries,m,p)
  except Exception as exc:logger.info("FAST_CORE_ODDS_OPTIONAL_FAILED %s: %s",m.event_id,exc);recs=[];market={"available":False}
  text=lc._format_strategy_signal(m,p,s,recs,goals,"signal",route,master,hz,market)
  if not lc._send(m,p,recs,text):continue
  unified_bot._record_live(m,p,s,recs,"signal")
  state[f"TRACK:{m.event_id}"]={"tracked_since":time.time(),"ts":time.time(),"score":f"{m.home_score}:{m.away_score}","minute":m.minute,"pressure":p.score,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"window":lc._window_id(m.minute),"post_goal_pending":False};sent+=1
 unified_bot._save_sent(state);logger.info("FAST_CORE_DIAG live=%d timed=%d shortlisted=%d evaluated=%d sent=%d tracked=%d",len(live),len(pending),shortlisted,evaluated,sent,sum(1 for k in state if str(k).startswith("TRACK:")));return sent
unified_bot.scan_live_once=scan_live_once_fast
