"""Reconcile GOOL CORE signal quality independently from displayed odds/bet.

The analytical signal is a goal-pressure call: it wins when at least one new goal
arrives after entry and loses when the match finishes without one. If a concrete
card bet was available, its settlement is stored separately as bet_* metadata.
"""
from __future__ import annotations
import logging,time
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals,update_signal
from market_settlement import settle_primary
logger=logging.getLogger("core_signal_reconcile")

def _score(v):
 try:a,b=str(v or "0:0").split(":",1);return int(a),int(b)
 except:return 0,0

def _bet_fields(primary,score):
 if not isinstance(primary,dict):return {}
 settlement=settle_primary(primary,score) or {}
 out={"bet_result":settlement.get("result"),"bet_pnl_units":settlement.get("pnl_units"),"bet_settled_market":settlement.get("settled_market"),"bet_settled_line":settlement.get("settled_line"),"bet_settled_odd":settlement.get("settled_odd")}
 return {k:v for k,v in out.items() if v is not None}

def reconcile(live)->int:
 live_by={str(m.event_id):m for m in live};now=time.time();fixed=0
 for row in all_signals():
  if row.get("kind")!="live" or str(row.get("reason") or "") not in {"signal","reentry"}:continue
  if str(row.get("result") or "pending").strip().lower()!="pending":continue
  eid=str(row.get("event_id") or "");sh,sa=_score(row.get("score_at_signal"));m=live_by.get(eid)
  if m:
   fh,fa=int(m.home_score),int(m.away_score);score=f"{fh}:{fa}"
   if fh+fa<=sh+sa:continue
   fields={"result":"win","signal_result":"win","next_goal_hit":True,"final_score":score,"settled_ts":int(now),"result_source":"goal_after_signal"}
   fields.update(_bet_fields(row.get("primary"),score))
   if update_signal(str(row.get("dedupe_key") or ""),**fields):fixed+=1;logger.info("CORE_SIGNAL_WIN %s %s",eid,score)
   continue
  age=now-float(row.get("created_ts",0) or 0)
  if age<12*60:continue
  try:
   body=fetch_summary(eid)
   if not body:continue
   fh,fa,_,_=_score_from_summary(body);score=f"{fh}:{fa}"
  except Exception as exc:
   logger.info("CORE_SIGNAL_SUMMARY_FAILED %s: %s",eid,exc);continue
  hit=(fh+fa)>(sh+sa)
  fields={"result":"win" if hit else "loss","signal_result":"win" if hit else "loss","next_goal_hit":hit,"final_score":score,"settled_ts":int(now),"result_source":"final_goal_after_signal" if hit else "final_no_goal_after_signal"}
  fields.update(_bet_fields(row.get("primary"),score))
  if update_signal(str(row.get("dedupe_key") or ""),**fields):fixed+=1;logger.info("CORE_SIGNAL_SETTLED %s %s result=%s",eid,score,fields["result"])
 return fixed
