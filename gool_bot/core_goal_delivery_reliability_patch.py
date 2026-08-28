"""Guarantee CORE goal-card delivery without confirming a goal that happened before entry.

A live score increase may reflect a score/journal sync lag.  Never use the current
match minute as the goal minute: fetch the summary, extract the actual last goal
minute, and only schedule confirmation when that goal is strictly after ENTRY.
"""
from __future__ import annotations
import logging,time
import core_primary_reconcile as cpr
import fast_goal_watch
import score_sync_patch
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
            # A list-score ahead of the journal is NOT enough proof of a new goal.
            # Read the summary and use the actual last-goal minute.  This prevents a
            # pre-entry goal from being confirmed one minute after a freshly sent signal.
            try:
                body=fetch_summary(eid)
                current,goal_minute=score_sync_patch._summary_state(body)
            except Exception as exc:
                log.info("CORE_GOAL_VERIFY_FAILED %s: %s",eid,exc);continue
            if current is None or sum(current)<=sh+sa:
                continue
            if not fast_goal_watch._goal_is_after_entry(row,goal_minute):
                log.warning("CORE_STALE_GOAL_NOT_CONFIRMED %s entry=%s score=%s current=%s goal_minute=%s",eid,row.get("minute"),row.get("score_at_signal"),current,goal_minute)
                continue
            scheduled=fast_goal_watch._schedule_direct(row,current,goal_minute)
            if scheduled:
                log.info("CORE_GOAL_CARD_QUEUED_BEFORE_SETTLE %s %s:%s goal=%s'",eid,current[0],current[1],goal_minute)
            else:
                log.warning("CORE_GOAL_CARD_QUEUE_FAILED %s %s:%s; keeping pending",eid,current[0],current[1])
            continue

        # Match disappeared: keep the conservative final-settlement path.
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
log.info("CORE goal delivery reliability active | stale pre-entry goals rejected")
