"""Keep CORE entry cards synchronized without blocking valid signals.

telegram_image_signal_patch used to launch a second full discover_live_matches()
inside a worker thread immediately before every entry. On a busy feed that refresh
can exceed its timeout; a perfectly valid CORE entry was then discarded with
ENTRY_SIGNAL_DEFERRED / ENTRY_CARD_SKIPPED_NO_FRESH_LIVE.

The Match passed to the sender already comes from the current production LIVE scan
(and score_sync_patch has already reconciled it against Flashscore summary). Reuse
that current snapshot and apply the already-attached authoritative summary score.
This removes a redundant network gate while preserving score synchronization.
"""
from __future__ import annotations
import copy
import logging

import telegram_image_signal_patch as tip

logger = logging.getLogger("entry_sync_failopen_patch")


def _sync_current_scan(match):
    if match is None:
        return None
    synced = copy.copy(match)

    # score_sync_patch attaches the current authoritative summary score to every
    # discovered match. Prefer it when available, including VAR rollbacks.
    summary_score = getattr(match, "summary_score", None)
    if isinstance(summary_score, (tuple, list)) and len(summary_score) >= 2:
        try:
            synced.home_score = int(summary_score[0])
            synced.away_score = int(summary_score[1])
        except (TypeError, ValueError):
            pass

    # If the summary has a goal minute newer than the list minute, never show a
    # card timestamp that predates that confirmed event.
    last_goal = getattr(match, "summary_last_goal_minute", None)
    try:
        if last_goal is not None and int(last_goal) > int(getattr(synced, "minute", 0) or 0):
            synced.minute = int(last_goal)
    except (TypeError, ValueError):
        pass

    logger.info(
        "ENTRY_SYNC_CURRENT_SCAN %s minute=%s score=%s:%s",
        getattr(synced, "event_id", "?"),
        getattr(synced, "minute", "?"),
        getattr(synced, "home_score", "?"),
        getattr(synced, "away_score", "?"),
    )
    return synced


tip._sync_entry_match = _sync_current_scan
