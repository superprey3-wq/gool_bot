"""Persist auditable runtime truth for GOOL CORE entries."""
from __future__ import annotations
import re,time,logging
import live_candidate_patch as lc
import unified_bot
from signal_journal import all_signals,update_signal
from market_settlement import fully_won_now,settle_primary
logger=logging.getLogger("signal_journal_runtime_patch")
_PENDING_META={};_orig_send=lc._send;_orig_record=unified_bot._record_live

def _score_total(value):
    try:a,b=str(value or "0:0").split(":",1);return int(a)+int(b)
    except Exception:return 0

def _parse_meta(text):
    mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text or "")
    return float(mm.group(1)) if mm else None

def _existing_real_entries(eid):
    return sorted([r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==str(eid) and str(r.get("reason") or "signal") in {"signal","reentry"}],key=lambda x:int(x.get("created_ts",0) or 0))

def _should_be_reentry(eid,current_score):
    current_total=_score_total(current_score)
    for row in reversed(_existing_real_entries(eid)):
        if str(row.get("result") or "pending").strip().lower() in {"+","win","won"} and current_total>_score_total(row.get("score_at_signal")):return True
    return False

def reconcile_reentry_labels():
    rows=all_signals();by_event={};fixed=0
    for row in rows:
        if row.get("kind")=="live" and str(row.get("reason") or "signal") in {"signal","reentry"}:by_event.setdefault(str(row.get("event_id") or ""),[]).append(row)
    for eid,items in by_event.items():
        items.sort(key=lambda x:int(x.get("created_ts",0) or 0));prior=None
        for i,row in enumerate(items):
            total=_score_total(row.get("score_at_signal"))
            if i and str(row.get("reason") or "signal")=="signal" and prior is not None and total>prior:
                if update_signal(str(row.get("dedupe_key") or ""),reason="reentry",reentry_reconciled=True):fixed+=1
            prior=max(prior or 0,total)
    return fixed

def _send(m,p,recs,text):
    if text and "МОЖНО" in text and "ЗАХОД" in text:_PENDING_META[(str(getattr(m,"event_id","")),int(getattr(m,"minute",0) or 0))]={"master":_parse_meta(text),"captured_ts":time.time()}
    return _orig_send(m,p,recs,text)

def _record(m,p,s,recs,reason):
    eid=str(getattr(m,"event_id","") or "");minute=int(getattr(m,"minute",0) or 0);current_score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";record_reason=reason
    if reason=="signal" and _should_be_reentry(eid,current_score):record_reason="reentry"
    result=_orig_record(m,p,s,recs,record_reason)
    if record_reason in {"signal","reentry"}:
        meta=_PENDING_META.pop((eid,minute),{});candidates=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and int(r.get("minute") or 0)==minute and str(r.get("reason") or "signal") in {"signal","reentry"}]
        if candidates:
            row=max(candidates,key=lambda x:int(x.get("created_ts",0) or 0));fields={"journal_version":4,"stake_units":1.0,"next_goal_hit":False}
            if meta.get("master") is not None:fields["master"]=float(meta["master"])
            update_signal(str(row.get("dedupe_key")),**fields)
    return result

def mark_latest_entry_goal(event_id,final_score=None,goal_minute=None):
    """Record the next goal; settle only if the stored primary market is actually won."""
    eid=str(event_id or "");rows=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and str(r.get("reason") or "signal") in {"signal","reentry"} and str(r.get("result") or "pending").strip().lower()=="pending"]
    if not rows:return False
    row=max(rows,key=lambda x:int(x.get("created_ts",0) or 0));fields={"next_goal_hit":True,"next_goal_confirmed_ts":int(time.time())}
    if final_score:fields["next_goal_score"]=str(final_score)
    if goal_minute is not None:fields["next_goal_minute"]=int(goal_minute)
    primary=row.get("primary")
    if final_score and fully_won_now(primary,final_score):
        settled=settle_primary(primary,final_score) or {};fields.update(settled,result_source="primary_market_crossed",settled_ts=int(time.time()),final_score=str(final_score))
    ok=update_signal(str(row.get("dedupe_key")),**fields)
    if ok:logger.info("JOURNAL_GOAL_CONFIRMED %s settled=%s",eid,fields.get("result","pending"))
    return ok

# Compatibility name for older callers; semantics are intentionally corrected.
mark_latest_entry_win=mark_latest_entry_goal
try:reconcile_reentry_labels()
except Exception:logger.exception("CORE reentry history reconciliation failed")
lc._send=_send;unified_bot._record_live=_record
