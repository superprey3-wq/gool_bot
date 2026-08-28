"""Guarantee CORE goal-card delivery before live reconciliation closes the journal row.

Previously core_primary_reconcile could mark a live CORE row WIN immediately after a
score change. The confirmation worker then woke up, found no pending row, and skipped
the green card. Route live score growth through the existing VAR-safe fast goal watcher
instead. Final/disappeared-match settlement remains unchanged.
"""
from __future__ import annotations
import logging,time
import core_primary_reconcile as cpr
import fast_goal_watch
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals,update_signal

log=logging.getLogger("core_goal_delivery_reliability")


def reconcile(live)->int:
    live_by={str(m.event_id):m for m in (live or [])}
    now=time.time();fixed=0
    for row in all_signals():
        if row.get("kind")!="live" or str(row.get("reason") or "") not in {"signal","reentry"}:
            continue
        if str(row.get("result") or "pending").strip().lower()!="pending":
            continue
        eid=str(row.get("event_id") or "")
        sh,sa=cpr._score(row.get("score_at_signal"))
        m=live_by.get(eid)
        if m:
            fh,fa=int(m.home_score),int(m.away_score)
            if fh+fa<=sh+sa:
                continue
            # Critical: do NOT settle here. Schedule the same confirmation path that
            # sends the green card; that worker marks the journal only after VAR-safe
            # verification. This removes the journal-vs-card race.
            scheduled=fast_goal_watch._schedule_direct(row,(fh,fa),int(getattr(m,"minute",0) or 0))
            if scheduled:
                log.info("CORE_GOAL_CARD_QUEUED_BEFORE_SETTLE %s %s:%s",eid,fh,fa)
            else:
                log.warning("CORE_GOAL_CARD_QUEUE_FAILED %s %s:%s; keeping pending",eid,fh,fa)
            continue

        # Match disappeared: keep the previous conservative final-settlement path.
        age=now-float(row.get("created_ts",0) or 0)
        if age<12*60:
            continue
        try:
            body=fetch_summary(eid)
            if not body:
                continue
            fh,fa,_,_=_score_from_summary(body);score=f"{fh}:{fa}"
        except Exception as exc:
            log.info("CORE_SIGNAL_SUMMARY_FAILED %s: %s",eid,exc);continue
        hit=(fh+fa)>(sh+sa)
        fields={"result":"win" if hit else "loss","signal_result":"win" if hit else "loss","next_goal_hit":hit,
                "final_score":score,"settled_ts":int(now),
                "result_source":"final_goal_after_signal" if hit else "final_no_goal_after_signal"}
        fields.update(cpr._bet_fields(row.get("primary"),score))
        if update_signal(str(row.get("dedupe_key") or ""),**fields):
            fixed+=1;log.info("CORE_SIGNAL_SETTLED_FINAL %s %s result=%s",eid,score,fields["result"])
    return fixed

cpr.reconcile=reconcile
log.info("CORE goal delivery reliability active | live WIN settles only through confirmation card path")
