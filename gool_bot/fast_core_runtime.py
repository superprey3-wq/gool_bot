"""Fast single-pass GOOL CORE runtime with transparent reject diagnostics."""
from __future__ import annotations
import logging,time
from collections import Counter
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
def _tot(s,k):
 try:a,b=s.get(k,(0,0));return float(a)+float(b)
 except:return 0.0
def _core_reject(code,m,p=None,cheap=None,master=None,grade=None,sc=None,market=None,detail="",near=False):
 sc=sc or {};market=market or {}
 strong=[f"{k}:{float(v):.0f}" for k,v in sc.items() if k not in {"HOME_PRESSURE","AWAY_PRESSURE","MARKET_VALUE"} and float(v or 0)>=72]
 corroborated=[f"{k}:{float(v):.0f}" for k,v in sc.items() if k not in {"HOME_PRESSURE","AWAY_PRESSURE","MARKET_VALUE"} and float(v or 0)>=64]
 logger.info("CORE_REJECT code=%s near_miss=%s %d' %s — %s %d:%d cheap=%s master=%s grade=%s pressure=%s strong=%s corroborated=%s market_available=%s edge=%s %s",code,int(bool(near)),int(getattr(m,"minute",0) or 0),m.home,m.away,m.home_score,m.away_score,"—" if cheap is None else f"{cheap:.0f}","—" if master is None else f"{master:.0f}",grade or "—","—" if p is None else f"{float(getattr(p,'score',0) or 0):.0f}",strong or [],corroborated or [],bool(market.get("available")),market.get("edge_pp"),detail)
async def scan_live_once_fast():
 live=await unified_bot.discover_live_matches();state=unified_bot._load_sent();sent=0;ids={str(m.event_id) for m in live};rejects=Counter()
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
  if not s:
   rejects["NO_STATS"]+=1;_core_reject("NO_STATS",m);continue
  prev=get_previous_values(m.event_id,m.minute,8);p=calculate_goal_pressure(m,s,prev)
  try:save_snapshot(m.event_id,StatsSnapshot(int(time.time()),m.minute,s))
  except Exception as exc:logger.info("FAST_CORE_SNAPSHOT_FAILED %s: %s",m.event_id,exc)
  cheap=max(float(p.score),float(lc._dom(m,s)),float(lc._threat(s)),float(lc._under(m,s)))
  if cheap<CHEAP_PREFILTER:
   rejects["CHEAP_PREFILTER"]+=1;near=cheap>=CHEAP_PREFILTER-5;_core_reject("CHEAP_PREFILTER",m,p,cheap,detail=f"required={CHEAP_PREFILTER:.0f} xg={_tot(s,'xg'):.2f} shots={_tot(s,'shots'):.0f} sot={_tot(s,'shots_on_target'):.0f}",near=near);continue
  shortlisted+=1;goals=_candidate_summary(m);recs=[];market={"available":False};qualifies,route,master,sc,hz,market=lc._evaluate(m,s,p,goals,market);evaluated+=1;grade=lc._signal_grade(master)
  logger.info("FAST_CORE_EVAL %d' %s — %s %d:%d cheap=%.0f master=%.0f grade=%s %s",m.minute,m.home,m.away,m.home_score,m.away_score,cheap,master,grade,"PASS" if qualifies else "REJECT")
  if not qualifies:
   strong=sum(1 for k,v in sc.items() if k not in {"HOME_PRESSURE","AWAY_PRESSURE","MARKET_VALUE"} and float(v or 0)>=72);corr=sum(1 for k,v in sc.items() if k not in {"HOME_PRESSURE","AWAY_PRESSURE","MARKET_VALUE"} and float(v or 0)>=64);code="NO_STRONG_CONFIRMATION" if strong==0 and corr<3 else "MODEL_REJECT";near=(master>=lc.ENTRY_MIN_SCORE-5 or corr>=2 or strong>=1);rejects[code]+=1;_core_reject(code,m,p,cheap,master,grade,sc,market,f"qualify_rule=strong>=1 OR corroborated>=3; actual strong={strong} corroborated={corr}; xg={_tot(s,'xg'):.2f} shots={_tot(s,'shots'):.0f} sot={_tot(s,'shots_on_target'):.0f} big={_tot(s,'big_chances'):.0f}",near);continue
  if grade not in {"ENTRY","STRONG"}:
   rejects["GRADE"]+=1;_core_reject("GRADE",m,p,cheap,master,grade,sc,market,f"required ENTRY>={lc.ENTRY_MIN_SCORE} STRONG>={lc.STRONG_MIN_SCORE}",master>=lc.ENTRY_MIN_SCORE-5);continue
  try:entries=unified_bot._fetch_event_odds(m.event_id);recs,market=lc._market(entries,m,p)
  except Exception as exc:
   rejects["ODDS_FETCH"]+=1;logger.info("FAST_CORE_ODDS_OPTIONAL_FAILED %s: %s",m.event_id,exc);recs=[];market={"available":False};_core_reject("ODDS_FETCH",m,p,cheap,master,grade,sc,market,str(exc),near=True)
  if not recs or not market.get("available"):
   rejects["NO_MARKET"]+=1;_core_reject("NO_MARKET",m,p,cheap,master,grade,sc,market,f"entries={len(entries) if 'entries' in locals() and entries is not None else 0} recs={len(recs)}",near=True)
  else:
   best=next((r for r in recs if r.get("best_bet")),None);logger.info("CORE_MARKET %d' %s — %s best=%s line=%s odd=%s confidence=%s edge=%s source=%s",m.minute,m.home,m.away,(best or {}).get("target_label"),(best or {}).get("line"),(best or {}).get("odd"),(best or {}).get("confidence"),(best or {}).get("value_edge"),(best or {}).get("source"))
  text=lc._format_strategy_signal(m,p,s,recs,goals,"signal",route,master,hz,market)
  if not text:
   rejects["FORMAT_SUPPRESS"]+=1;_core_reject("FORMAT_SUPPRESS",m,p,cheap,master,grade,sc,market,near=True);continue
  if not lc._send(m,p,recs,text):
   rejects["SEND_REJECT"]+=1;_core_reject("SEND_REJECT",m,p,cheap,master,grade,sc,market,"telegram/filter/send returned false",near=True);continue
  unified_bot._record_live(m,p,s,recs,"signal")
  state[f"TRACK:{m.event_id}"]={"tracked_since":time.time(),"ts":time.time(),"score":f"{m.home_score}:{m.away_score}","minute":m.minute,"pressure":p.score,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"window":lc._window_id(m.minute),"post_goal_pending":False};sent+=1
 unified_bot._save_sent(state);logger.info("FAST_CORE_DIAG live=%d timed=%d shortlisted=%d evaluated=%d sent=%d tracked=%d rejects=%s",len(live),len(pending),shortlisted,evaluated,sent,sum(1 for k in state if str(k).startswith("TRACK:")),dict(rejects));return sent
unified_bot.scan_live_once=scan_live_once_fast
