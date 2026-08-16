"""Persist runtime truth for GOOL entries.

This patch does not change signal selection. It enriches the signal journal with
runtime metadata, marks confirmed goals as wins, and keeps post-goal CORE entries
classified as reentries rather than new primary signals.
"""
from __future__ import annotations
import re,time,logging
import live_candidate_patch as lc
import unified_bot
from signal_journal import all_signals,update_signal
logger=logging.getLogger("signal_journal_runtime_patch")

_PENDING_META={}
_orig_send=lc._send
_orig_record=unified_bot._record_live

def _score_total(value):
    try:
        a,b=str(value or "0:0").split(":",1);return int(a)+int(b)
    except Exception:return 0

def _parse_meta(text):
    mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text or "")
    return float(mm.group(1)) if mm else None

def _existing_real_entries(eid):
    return sorted(
        [r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==str(eid) and str(r.get("reason") or "signal") in {"signal","reentry"}],
        key=lambda x:int(x.get("created_ts",0) or 0),
    )

def _should_be_reentry(eid,current_score):
    rows=_existing_real_entries(eid)
    if not rows:return False
    current_total=_score_total(current_score)
    # A new real CORE entry for an event that already had a completed winning entry,
    # and whose score has advanced, is necessarily a post-goal reentry.
    for row in reversed(rows):
        result=str(row.get("result") or "pending").strip().lower()
        if result in {"+","win","won"} and current_total>_score_total(row.get("score_at_signal")):
            return True
    return False

def reconcile_reentry_labels():
    """Repair old rows created by the historic bug that recorded reentry as signal."""
    rows=all_signals();by_event={}
    for row in rows:
        if row.get("kind")!="live" or str(row.get("reason") or "signal") not in {"signal","reentry"}:continue
        by_event.setdefault(str(row.get("event_id") or ""),[]).append(row)
    fixed=0
    for eid,items in by_event.items():
        items.sort(key=lambda x:int(x.get("created_ts",0) or 0))
        seen_entry=False;prior_score_total=None
        for row in items:
            reason=str(row.get("reason") or "signal")
            score_total=_score_total(row.get("score_at_signal"))
            if not seen_entry:
                seen_entry=True;prior_score_total=score_total;continue
            if reason=="signal" and prior_score_total is not None and score_total>prior_score_total:
                if update_signal(str(row.get("dedupe_key") or ""),reason="reentry",journal_version=3,reentry_reconciled=True):
                    fixed+=1
                    logger.warning("CORE_REENTRY_RECONCILED %s %s — %s at %s'",eid,row.get("home"),row.get("away"),row.get("minute"))
            prior_score_total=max(prior_score_total or 0,score_total)
    if fixed:logger.warning("CORE_REENTRY_RECONCILE_TOTAL fixed=%d",fixed)
    return fixed

def _send(m,p,recs,text):
    if text and "МОЖНО" in text and "ЗАХОД" in text:
        _PENDING_META[(str(getattr(m,"event_id","")),int(getattr(m,"minute",0) or 0))]={"master":_parse_meta(text),"captured_ts":time.time()}
    return _orig_send(m,p,recs,text)

def _record(m,p,s,recs,reason):
    eid=str(getattr(m,"event_id","") or "");minute=int(getattr(m,"minute",0) or 0);current_score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}"
    record_reason=reason
    if reason=="signal" and _should_be_reentry(eid,current_score):
        record_reason="reentry"
        logger.info("CORE_REENTRY_CLASSIFIED %s %s — %s at %d' score=%s",eid,getattr(m,"home",""),getattr(m,"away",""),minute,current_score)
    result=_orig_record(m,p,s,recs,record_reason)
    if record_reason in {"signal","reentry"}:
        meta=_PENDING_META.pop((eid,minute),{})
        candidates=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and int(r.get("minute") or 0)==minute and str(r.get("reason") or "signal") in {"signal","reentry"}]
        if candidates:
            row=max(candidates,key=lambda x:int(x.get("created_ts",0) or 0));fields={"journal_version":3}
            if meta.get("master") is not None:fields["master"]=float(meta["master"])
            update_signal(str(row.get("dedupe_key")),**fields)
    return result

def mark_latest_entry_win(event_id,final_score=None,goal_minute=None):
    """Mark exactly one latest still-pending real entry for this match as won."""
    eid=str(event_id or "")
    rows=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and str(r.get("reason") or "signal") in {"signal","reentry"} and str(r.get("result") or "pending").strip().lower() not in {"+","win","won"}]
    if not rows:return False
    row=max(rows,key=lambda x:int(x.get("created_ts",0) or 0));fields={"result":"+","result_source":"confirmed_live_goal","confirmed_ts":int(time.time())}
    if final_score:fields["final_score"]=str(final_score)
    if goal_minute is not None:fields["goal_minute"]=int(goal_minute)
    ok=update_signal(str(row.get("dedupe_key")),**fields)
    if ok:logger.info("JOURNAL_WIN_CONFIRMED %s %s — %s",eid,row.get("home"),row.get("away"))
    return ok

# Repair already stored history once at startup, then keep future rows correct.
try:reconcile_reentry_labels()
except Exception:logger.exception("CORE reentry history reconciliation failed")
lc._send=_send
unified_bot._record_live=_record
