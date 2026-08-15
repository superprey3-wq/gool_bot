"""Synchronize only shortlisted CORE entry cards.

The expensive full LIVE re-scan before every card is gone.  For an entry that has already
passed analytics we do one lightweight summary request, reconcile the score (including VAR
rollback), and keep the fresh list minute from the current discovery cycle.
"""
from __future__ import annotations
import copy
import logging

from live_engine import fetch_summary
import score_sync_patch
import telegram_image_signal_patch as tip

logger=logging.getLogger("entry_sync_failopen_patch")


def _sync_current_scan(match):
    if match is None:return None
    synced=copy.copy(match)
    try:
        body=fetch_summary(str(getattr(match,"event_id","") or ""))
        score,last_goal=score_sync_patch._summary_state(body)
        if score is not None:
            synced.home_score=int(score[0]);synced.away_score=int(score[1])
            synced.summary_score=score
        if last_goal is not None:
            synced.summary_last_goal_minute=int(last_goal)
            if int(last_goal)>int(getattr(synced,"minute",0) or 0):synced.minute=int(last_goal)
    except Exception as exc:
        # Fail open: the current LIVE list is already fresh enough for an actionable card.
        logger.info("ENTRY_LIGHT_SYNC_FAILED %s: %s",getattr(match,"event_id","?"),exc)
    logger.info("ENTRY_SYNC_CURRENT_SCAN %s minute=%s score=%s:%s",getattr(synced,"event_id","?"),getattr(synced,"minute","?"),getattr(synced,"home_score","?"),getattr(synced,"away_score","?"))
    return synced


tip._sync_entry_match=_sync_current_scan
