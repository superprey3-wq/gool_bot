"""Synchronize Flashscore live-card state with event summary before analysis.

The football live list can lag behind df_sui by one refresh. Downstream LIVE
logic must never evaluate a stale score or a clock that predates an already
registered goal. This patch reconciles both cumulative score and latest goal
minute before any signal/odds calculation runs.
"""
from __future__ import annotations

import logging
import re

import unified_bot
from live_engine import fetch_summary

logger = logging.getLogger("score_sync_patch")
_orig_discover = unified_bot.discover_live_matches


def _summary_state(body: str) -> tuple[tuple[int, int] | None, int | None]:
    """Return cumulative score and latest minute from a real score-changing event."""
    if not body:
        return None, None

    home = away = 0
    seen_score = False
    last_goal_minute: int | None = None

    for chunk in body.split("~III"):
        hm = re.search(r"INX(?:÷|¬)(\d+)", chunk)
        am = re.search(r"IOX(?:÷|¬)(\d+)", chunk)
        if not hm and not am:
            continue

        prev_home, prev_away = home, away
        new_home = int(hm.group(1)) if hm else home
        new_away = int(am.group(1)) if am else away
        seen_score = True

        # Score fields in summary can also appear on non-goal rows. A goal minute
        # is accepted only if this particular row actually increases the score.
        score_changed = new_home > prev_home or new_away > prev_away
        home = max(home, new_home)
        away = max(away, new_away)

        if score_changed:
            mm = re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:\+(\d{1,2}))?", chunk)
            if mm:
                base = int(mm.group(1))
                added = int(mm.group(2) or 0)
                minute = base + added
                last_goal_minute = minute if last_goal_minute is None else max(last_goal_minute, minute)

    return ((home, away) if seen_score else None), last_goal_minute


async def _discover_synced():
    matches = await _orig_discover()
    for match in matches:
        try:
            body = fetch_summary(match.event_id)
            score, last_goal_minute = _summary_state(body)
        except Exception as exc:
            logger.info("SUMMARY_STATE_SYNC_FAILED %s: %s", match.event_id, exc)
            continue

        # Attach diagnostics without changing the LiveMatch dataclass contract.
        match.summary_last_goal_minute = last_goal_minute

        if score:
            sh, sa = score
            old_total = int(match.home_score) + int(match.away_score)
            new_total = sh + sa

            # Move score only forward. Never let an older/incomplete summary
            # overwrite a newer live-card score.
            if new_total > old_total:
                old = f"{match.home_score}:{match.away_score}"
                match.home_score, match.away_score = sh, sa
                match.summary_goal_ahead = True
                logger.warning(
                    "STALE_SCORE_FIXED %s %s — %s | %s -> %d:%d | last_goal=%s",
                    match.event_id, match.home, match.away, old, sh, sa,
                    last_goal_minute if last_goal_minute is not None else "?",
                )
            else:
                match.summary_goal_ahead = False
        else:
            match.summary_goal_ahead = False

        # The displayed clock may never be behind a goal summary already confirms.
        # Example: live card says 51', summary already contains a goal at 52'.
        if last_goal_minute is not None and int(match.minute) < last_goal_minute:
            old_minute = int(match.minute)
            match.minute = last_goal_minute
            logger.warning(
                "STALE_MINUTE_FIXED %s %s — %s | %d' -> %d' due to confirmed goal",
                match.event_id, match.home, match.away, old_minute, match.minute,
            )

    return matches


unified_bot.discover_live_matches = _discover_synced
