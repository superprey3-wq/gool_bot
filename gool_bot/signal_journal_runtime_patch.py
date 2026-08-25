"""Persist auditable runtime truth for GOOL CORE entries."""
from __future__ import annotations
import re,time,logging
import live_candidate_patch as lc
import unified_bot
from signal_journal import all_signals,update_signal
from market_settlement import fully_won_now,settle_primary
logger=logging.getLogger("signal_journal_runtime_patch");_PENDING_META={};_orig_send=lc._send;_orig_record=unified_bot._record_live
_PENDING={"","pending","wait","waiting"}
def _score_total(v):
 try:a,b=str(v or "0:0").split(":",1);return int(a)+int(b)
 except:return 0
def _parse_meta(text):
 m=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text or "");return float(m.group(1)) if m else None
def _existing(eid):return sorted([r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==str(eid) and str(r.get("reason") or "signal") in {"signal","reentry"}],key=lambda x:int(x.get("created_ts",0) or 0))
def _should_reentry(eid,score):
 total=_score_total(score)
 return any(str(r.get("result") or "pending").lower() in {"+","win","won"} and total>_score_total(r.get("score_at_signal")) for r in reversed(_existing(eid)))
def _selected_primary(recs):
 r=next((x for x in recs or [] if x.get("best_concrete_bet")),None) or next((x for x in recs or [] if x.get("best_bet")),None)
 if not r:return None
 p=dict(r);kind=str(p.get("market_type") or "")
 if kind:p["market"]=kind
 elif p.get("line") is not None:p["market"]="TOTAL_OVER"
 return p
def reconcile_reentry_labels():
 rows=all_signals();by={};fixed=0
 for r in rows:
  if r.get("kind")=="live" and str(r.get("reason") or "signal") in {"signal","reentry"}:by.setdefault(str(r.get("event_id") or ""),[]).append(r)
 for eid,items in by.items():
  items.sort(key=lambda x:int(x.get("created_ts",0) or 0));prior=None
  for i,r in enumerate(items):
   total=_score_total(r.get("score_at_signal"))
   if i and str(r.get("reason") or "signal")=="signal" and prior is not None and total>prior:
    if update_signal(str(r.get("dedupe_key") or ""),reason="reentry",reentry_reconciled=True):fixed+=1
   prior=max(prior or 0,total)
 return fixed
def _send(m,p,recs,text):
 if text and "МОЖНО" in text and "ЗАХОД" in text:_PENDING_META[(str(getattr(m,"event_id","")),int(getattr(m,"minute",0) or 0))]={"master":_parse_meta(text),"captured_ts":time.time()}
 return _orig_send(m,p,recs,text)
def _record(m,p,s,recs,reason):
 eid=str(getattr(m,"event_id","") or "");minute=int(getattr(m,"minute",0) or 0);score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";record_reason="reentry" if reason=="signal" and _should_reentry(eid,score) else reason;result=_orig_record(m,p,s,recs,record_reason)
 if record_reason in {"signal","reentry"}:
  meta=_PENDING_META.pop((eid,minute),{});c=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and int(r.get("minute") or 0)==minute and str(r.get("reason") or "signal") in {"signal","reentry"}]
  if c:
   row=max(c,key=lambda x:int(x.get("created_ts",0) or 0));fields={"journal_version":5,"stake_units":1.0,"next_goal_hit":False};primary=_selected_primary(recs)
   if primary:fields["primary"]=primary;fields["odd"]=primary.get("odd");fields["market_status"]=primary.get("external_market_status") or primary.get("market_status") or primary.get("market_consensus")
   if meta.get("master") is not None:fields["master"]=float(meta["master"])
   update_signal(str(row.get("dedupe_key")),**fields)
 return result
def mark_latest_entry_goal(event_id,final_score=None,goal_minute=None):
 eid=str(event_id or "");rows=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and str(r.get("reason") or "signal") in {"signal","reentry"} and str(r.get("result") or "pending").strip().lower() in _PENDING]
 if not rows:return False
 row=max(rows,key=lambda x:int(x.get("created_ts",0) or 0));fields={"next_goal_hit":True,"next_goal_confirmed_ts":int(time.time())}
 if final_score:fields["next_goal_score"]=str(final_score)
 if goal_minute is not None:fields["next_goal_minute"]=int(goal_minute)
 primary=row.get("primary")
 if final_score and fully_won_now(primary,final_score):fields.update(settle_primary(primary,final_score) or {},result_source="primary_market_crossed",settled_ts=int(time.time()),final_score=str(final_score))
 ok=update_signal(str(row.get("dedupe_key")),**fields)
 if ok:logger.info("JOURNAL_GOAL_CONFIRMED %s settled=%s",eid,fields.get("result","pending"))
 return ok
mark_latest_entry_win=mark_latest_entry_goal
try:reconcile_reentry_labels()
except Exception:logger.exception("CORE reentry history reconciliation failed")
lc._send=_send;unified_bot._record_live=_record
