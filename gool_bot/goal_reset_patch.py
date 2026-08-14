"""Close a completed LIVE signal after the next goal and start fresh next scan.

The existing engine still detects the goal and sends the green confirmation card.
After that scan finishes, any TRACK entry marked post_goal_pending is removed. On
the next 60-second LIVE cycle the same match is treated as a brand-new candidate
with the new score and fresh statistics.
"""
from __future__ import annotations

import logging
import unified_bot

logger = logging.getLogger("goal_reset_patch")
_orig_scan = unified_bot.scan_live_once

async def _scan_with_goal_reset():
    result = await _orig_scan()
    try:
        state = unified_bot._load_sent()
        removed = 0
        for key in list(state):
            row = state.get(key)
            if not str(key).startswith("TRACK:") or not isinstance(row, dict):
                continue
            # live_candidate_patch sets this only after it has detected a changed
            # score and successfully sent/recorded the goal confirmation.
            if row.get("post_goal_pending"):
                state.pop(key, None)
                removed += 1
        if removed:
            unified_bot._save_sent(state)
            logger.info("GOAL_RESET closed %d completed signal track(s); next scan starts fresh", removed)
    except Exception:
        logger.exception("GOAL_RESET failed; original LIVE scan result is preserved")
    return result

unified_bot.scan_live_once = _scan_with_goal_reset
