"""Keep Flashscore live-card score synchronized with event summary before analysis.

The football page can lag a goal by one scan while df_sui already contains the
new cumulative score.  Patch discover_live_matches so downstream signal/odds
logic never evaluates a stale score.
"""
from __future__ import annotations

import logging
import re

import unified_bot
from live_engine import fetch_summary

logger = logging.getLogger("score_sync_patch")
_orig_discover = unified_bot.discover_live_matches


def _summary_score(body: str) -> tuple[int, int] | None:
    if not body:
        return None
    home = away = 0
    seen = False
    for chunk in body.split("~III"):
        hm = re.search(r"INX(?:÷|¬)(\d+)", chunk)
        am = re.search(r"IOX(?:÷|¬)(\d+)", chunk)
        if not hm and not am:
            continue
        seen = True
        if hm:
            home = max(home, int(hm.group(1)))
        if am:
            away = max(away, int(am.group(1)))
    return (home, away) if seen else None


async def _discover_synced():
    matches = await _orig_discover()
    for match in matches:
        try:
            score = _summary_score(fetch_summary(match.event_id))
        except Exception as exc:
            logger.info("SUMMARY_SCORE_SYNC_FAILED %s: %s", match.event_id, exc)
            continue
        if not score:
            continue
        sh, sa = score
        # Only move the score forward. Never replace a newer live-card score
        # with an older/incomplete summary snapshot.
        if sh + sa > match.home_score + match.away_score:
            old = f"{match.home_score}:{match.away_score}"
            match.home_score, match.away_score = sh, sa
            logger.warning(
                "STALE_SCORE_FIXED %s %s — %s | %s -> %d:%d",
                match.event_id, match.home, match.away, old, sh, sa,
            )
    return matches


unified_bot.discover_live_matches = _discover_synced
