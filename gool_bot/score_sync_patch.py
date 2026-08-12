"""Synchronize Flashscore live-card state with event summary before analysis.

The football live list can lag behind df_sui by one refresh.  Downstream LIVE
logic must never evaluate a stale score or a clock that predates an already
registered goal.  This patch reconciles both cumulative score and latest goal
minute before any signal/odds calculation runs.
"""
from __future__ import annotations

import logging
import re

import unified_bot
from live_engine import fetch_summary, parse_goal_timeline

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


def _latest_goal_minute(body: str) -> int | None:
    """Return the latest goal minute known by summary, including 45+N/90+N."""
    latest: int | None = None

    # Prefer the project's existing goal parser so score-change semantics stay
    # identical to the LIVE engine.
    try:
        for item in parse_goal_timeline(body):
            m = re.match(r"(\d{1,3})'", str(item))
            if m:
                value = int(m.group(1))
                latest = value if latest is None else max(latest, value)
    except Exception:
        pass

    # Some feed variants expose added time in the raw IB/IBX value.  Accept a
    # simple 45+N / 90+N form as a defensive fallback.
    for chunk in (body or "").split("~III"):
        mm = re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:\+(\d{1,2}))?", chunk)
        hm = re.search(r"INX(?:÷|¬)(\d+)", chunk)
        am = re.search(r"IOX(?:÷|¬)(\d+)", chunk)
        if not mm or (not hm and not am):
            continue
        base = int(mm.group(1))
        added = int(mm.group(2) or 0)
        value = base + added
        latest = value if latest is None else max(latest, value)

    return latest


async def _discover_synced():
    matches = await _orig_discover()
    for match in matches:
        try:
            body = fetch_summary(match.event_id)
            score = _summary_score(body)
            last_goal_minute = _latest_goal_minute(body)
        except Exception as exc:
            logger.info("SUMMARY_STATE_SYNC_FAILED %s: %s", match.event_id, exc)
            continue

        # Keep diagnostics available to downstream patches without changing the
        # LiveMatch dataclass contract.
        match.summary_last_goal_minute = last_goal_minute

        if score:
            sh, sa = score
            old_total = int(match.home_score) + int(match.away_score)
            new_total = sh + sa

            # Only move score forward. Never let an older/incomplete summary
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

        # The displayed match clock may never be behind an event that summary
        # already confirms.  Example: card says 51' while summary has a goal at
        # 52'.  Advance to 52 so every probability/window calculation uses a
        # chronologically valid state.
        if last_goal_minute is not None and int(match.minute) < last_goal_minute:
            old_minute = int(match.minute)
            match.minute = last_goal_minute
            logger.warning(
                "STALE_MINUTE_FIXED %s %s — %s | %d' -> %d' due to summary goal",
                match.event_id, match.home, match.away, old_minute, match.minute,
            )

    return matches


unified_bot.discover_live_matches = _discover_synced
