"""Hard safety invariants for GOOL goal confirmations.

1. The score/minute shown on the final refreshed ENTRY card becomes the exact
   persistent journal baseline used by every confirmation path.
2. A known goal at/before the entry minute can never confirm that entry.
3. A confirmation candidate must have strictly more total goals than the exact
   journal score_at_signal.

This patch changes confirmation integrity only; it does not change signal gates.
"""
from __future__ import annotations

import logging
import time

import fast_goal_watch as fgw
import telegram_image_signal_patch as tip
from signal_journal import update_signal

logger = logging.getLogger("confirmation_integrity")

_orig_sync_entry_match = tip._sync_entry_match
_orig_schedule_direct = fgw._schedule_direct


def _score_tuple(value):
    try:
        a, b = str(value or "0:0").split(":", 1)
        return int(a), int(b)
    except Exception:
        return 0, 0


def _minute(value):
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _sync_entry_match(match):
    """Persist exactly the score/minute that will be shown on the ENTRY card."""
    synced = _orig_sync_entry_match(match)
    if synced is None:
        return None

    eid = str(getattr(synced, "event_id", "") or "")
    row = tip._pending_row(eid) if eid else None
    if not row:
        logger.warning("ENTRY_BASELINE_SYNC_NO_PENDING %s", eid)
        return synced

    key = str(row.get("dedupe_key") or "")
    new_score = f"{int(getattr(synced, 'home_score', 0) or 0)}:{int(getattr(synced, 'away_score', 0) or 0)}"
    new_minute = _minute(getattr(synced, "minute", 0))
    old_score = str(row.get("score_at_signal") or "0:0")
    old_minute = _minute(row.get("minute"))

    if key:
        ok = update_signal(
            key,
            score_at_signal=new_score,
            minute=new_minute,
            entry_baseline_synced=True,
            entry_baseline_sync_ts=int(time.time()),
        )
        if ok:
            if old_score != new_score or old_minute != new_minute:
                logger.warning(
                    "ENTRY_BASELINE_SYNC %s score %s -> %s minute %s -> %s",
                    eid, old_score, new_score, old_minute, new_minute,
                )
            else:
                logger.info("ENTRY_BASELINE_SYNC_OK %s %s %s'", eid, new_score, new_minute)
        else:
            logger.error("ENTRY_BASELINE_SYNC_FAILED %s key=%s", eid, key)
    return synced


def _goal_is_strictly_post_entry(row, current_score, goal_minute):
    before = _score_tuple(row.get("score_at_signal"))
    current = tuple(current_score)
    if sum(current) <= sum(before):
        logger.warning(
            "CONFIRM_INTEGRITY_REJECT_SCORE %s entry=%s current=%s",
            row.get("event_id", "?"), before, current,
        )
        return False

    gm = _minute(goal_minute)
    em = _minute(row.get("minute"))
    if gm and em and gm <= em:
        logger.warning(
            "CONFIRM_INTEGRITY_REJECT_MINUTE %s goal=%s' entry=%s' entry_score=%s current=%s",
            row.get("event_id", "?"), gm, em, before, current,
        )
        return False
    return True


def _schedule_direct(row, current_score, goal_minute):
    if not _goal_is_strictly_post_entry(row, current_score, goal_minute):
        return False
    return _orig_schedule_direct(row, current_score, goal_minute)


# Make the refreshed ENTRY card and journal use one identical baseline.
tip._sync_entry_match = _sync_entry_match

# Protect the independent fast watcher as well as the normal CORE worker.
fgw._schedule_direct = _schedule_direct
fgw._goal_is_strictly_post_entry = _goal_is_strictly_post_entry

logger.info(
    "Confirmation integrity active | ENTRY card == journal baseline | "
    "current goals must increase | known goal minute must be after ENTRY"
)
