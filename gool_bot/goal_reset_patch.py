"""Close a completed LIVE signal after the next confirmed goal and start fresh."""
from __future__ import annotations
import logging
import unified_bot
from signal_journal_runtime_patch import mark_latest_entry_win
logger=logging.getLogger("goal_reset_patch")
_orig_scan=unified_bot.scan_live_once

async def _scan_with_goal_reset():
    result=await _orig_scan()
    try:
        state=unified_bot._load_sent();removed=0
        for key in list(state):
            row=state.get(key)
            if not str(key).startswith("TRACK:") or not isinstance(row,dict):continue
            if row.get("post_goal_pending"):
                event_id=str(key).split(":",1)[1]
                mark_latest_entry_win(event_id,final_score=row.get("post_goal_score") or row.get("score"),goal_minute=row.get("post_goal_minute") or row.get("minute"))
                state.pop(key,None);removed+=1
        if removed:
            unified_bot._save_sent(state);logger.info("GOAL_RESET closed %d completed signal track(s); next scan starts fresh",removed)
    except Exception:logger.exception("GOAL_RESET failed; original LIVE scan result is preserved")
    return result

unified_bot.scan_live_once=_scan_with_goal_reset
