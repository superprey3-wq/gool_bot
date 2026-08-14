"""Persist runtime truth for GOOL entries.

This patch does not change signal selection. It only enriches the signal journal
with the actual MASTER/grade/route shown at entry and marks the latest pending
entry as a WIN when the bot has successfully sent a confirmed goal event.
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

def _parse_meta(text):
    mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text or "")
    master=float(mm.group(1)) if mm else None
    return master

def _send(m,p,recs,text):
    # Cache only actual entry messages. Goal/followup rows must never overwrite it.
    if text and "МОЖНО" in text and "ЗАХОД" in text:
        _PENDING_META[(str(getattr(m,"event_id","")),int(getattr(m,"minute",0) or 0))]={
            "master":_parse_meta(text),"captured_ts":time.time()
        }
    return _orig_send(m,p,recs,text)

def _record(m,p,s,recs,reason):
    result=_orig_record(m,p,s,recs,reason)
    if reason in {"signal","reentry"}:
        eid=str(getattr(m,"event_id",""));minute=int(getattr(m,"minute",0) or 0);meta=_PENDING_META.pop((eid,minute),{})
        # _record_live writes immediately, so update the newest matching entry.
        candidates=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and int(r.get("minute") or 0)==minute and str(r.get("reason") or "signal") in {"signal","reentry"}]
        if candidates:
            row=max(candidates,key=lambda x:int(x.get("created_ts",0) or 0));fields={"journal_version":2}
            if meta.get("master") is not None:fields["master"]=float(meta["master"])
            update_signal(str(row.get("dedupe_key")),**fields)
    return result

def mark_latest_entry_win(event_id,final_score=None,goal_minute=None):
    """Mark exactly one latest still-pending real entry for this match as won."""
    eid=str(event_id or "")
    rows=[r for r in all_signals() if r.get("kind")=="live" and str(r.get("event_id"))==eid and str(r.get("reason") or "signal") in {"signal","reentry"} and str(r.get("result") or "pending") not in {"+","win","WIN"}]
    if not rows:return False
    row=max(rows,key=lambda x:int(x.get("created_ts",0) or 0));fields={"result":"+","result_source":"confirmed_live_goal","confirmed_ts":int(time.time())}
    if final_score:fields["final_score"]=str(final_score)
    if goal_minute is not None:fields["goal_minute"]=int(goal_minute)
    ok=update_signal(str(row.get("dedupe_key")),**fields)
    if ok:logger.info("JOURNAL_WIN_CONFIRMED %s %s — %s",eid,row.get("home"),row.get("away"))
    return ok

lc._send=_send
unified_bot._record_live=_record
