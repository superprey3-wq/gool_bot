"""Keep GOOL TRACK state aligned with the signal journal after every LIVE scan.

The green-card confirmation runs asynchronously. A long LIVE scan may still hold an old
copy of live_sent.json in memory and save it after the green worker has already removed a
TRACK. That can resurrect a completed TRACK and make the same goal look new again on the
next scan. This patch removes those orphaned closed TRACKs after the core scan has saved.
"""
from __future__ import annotations
import logging
import unified_bot
from signal_journal import all_signals
from signal_journal_runtime_patch import mark_latest_entry_win
logger=logging.getLogger("goal_reset_patch")
_orig_scan=unified_bot.scan_live_once

_PENDING_VALUES={"","pending","wait","waiting"}
_WIN_VALUES={"+","win","won","success"}

def _journal_state(event_id):
    """Return (has_pending_entry, has_closed_win) for real LIVE entries of one event."""
    eid=str(event_id or "")
    pending=False;closed=False
    try:rows=all_signals()
    except Exception as exc:
        logger.warning("GOAL_RESET journal read failed for %s: %s",eid,exc);return False,False
    for r in rows:
        if r.get("kind")!="live" or str(r.get("event_id") or "")!=eid:continue
        if str(r.get("reason") or "signal") not in {"signal","reentry"}:continue
        result=str(r.get("result") or "pending").strip().lower()
        if result in _PENDING_VALUES:pending=True
        elif result in _WIN_VALUES:closed=True
    return pending,closed

async def _scan_with_goal_reset():
    result=await _orig_scan()
    try:
        state=unified_bot._load_sent();removed=0
        for key in list(state):
            row=state.get(key)
            if not str(key).startswith("TRACK:") or not isinstance(row,dict):continue
            event_id=str(key).split(":",1)[1]

            # Compatibility with the older synchronous post-goal flow.
            if row.get("post_goal_pending"):
                mark_latest_entry_win(event_id,final_score=row.get("post_goal_score") or row.get("score"),goal_minute=row.get("post_goal_minute") or row.get("minute"))
                state.pop(key,None);removed+=1
                logger.info("GOAL_RESET removed post-goal TRACK %s",event_id)
                continue

            # Async green-card race protection: if the journal says the real entry is
            # already closed and there is no newer pending entry, this TRACK is stale.
            pending,closed=_journal_state(event_id)
            if closed and not pending:
                state.pop(key,None);removed+=1
                logger.warning("GOAL_RESET purged resurrected closed TRACK %s",event_id)

        if removed:
            unified_bot._save_sent(state)
            logger.info("GOAL_RESET cleaned %d completed/orphaned signal track(s)",removed)
    except Exception:logger.exception("GOAL_RESET failed; original LIVE scan result is preserved")
    return result

unified_bot.scan_live_once=_scan_with_goal_reset
