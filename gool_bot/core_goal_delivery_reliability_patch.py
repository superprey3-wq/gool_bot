"""Guarantee CORE goal-card delivery without confirming a goal that happened before entry.

This patch also enforces two hard invariants:
1) the journal entry score/minute must be the exact fresh snapshot used by the entry card;
2) a green confirmation card can only be sent when the current total goals are strictly
   greater than the pending entry baseline.
"""
from __future__ import annotations
import logging,time
import core_primary_reconcile as cpr
import fast_goal_watch
import score_sync_patch
import telegram_image_signal_patch as tip
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals,update_signal

log=logging.getLogger("core_goal_delivery_reliability")

# The entry image patch refreshes the match before rendering, but historically it
# refreshed only a copy.  The journal recorder then received the stale original
# object and could store 2:1 while the visible card already showed 2:3.  Mutate the
# original object with that same fresh snapshot so card and journal share one truth.
_orig_sync_entry_match=tip._sync_entry_match
def _sync_entry_match_truth(match):
    synced=_orig_sync_entry_match(match)
    if synced is not None:
        try:
            tip._merge_live_fields(match,synced)
            log.info("CORE_ENTRY_CARD_JOURNAL_SYNC %s minute=%s score=%s:%s",
                     getattr(match,"event_id",""),getattr(match,"minute",None),
                     getattr(match,"home_score",0),getattr(match,"away_score",0))
        except Exception:
            log.exception("CORE_ENTRY_CARD_JOURNAL_SYNC_FAILED %s",getattr(match,"event_id",""))
    return synced
tip._sync_entry_match=_sync_entry_match_truth

# Last gate before Telegram delivery.  Even if any older TRACK/candidate state is
# stale, never show a green card unless score increased versus the actual pending
# entry row.  This directly blocks 2:3 -> 2:3 confirmations.
_orig_send_photo_all=tip._send_photo_all
def _send_photo_all_truth(match,pressure,recs,kind,master=None):
    if kind=="goal":
        eid=str(getattr(match,"event_id","") or "")
        row=tip._pending_row(eid)
        if row is None:
            log.warning("CORE_GOAL_CARD_REJECT_NO_PENDING %s",eid)
            return False
        entry=cpr._score(row.get("score_at_signal"))
        current=(int(getattr(match,"home_score",0) or 0),int(getattr(match,"away_score",0) or 0))
        if sum(current)<=sum(entry):
            log.error("CORE_GOAL_CARD_REJECT_SAME_SCORE %s entry=%s:%s current=%s:%s entry_minute=%s current_minute=%s",
                      eid,entry[0],entry[1],current[0],current[1],row.get("minute"),getattr(match,"minute",None))
            return False
    return _orig_send_photo_all(match,pressure,recs,kind,master)
tip._send_photo_all=_send_photo_all_truth


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
log.info("CORE goal delivery reliability active | card/journal same snapshot | same-score green cards blocked")
