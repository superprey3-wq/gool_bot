"""Synchronize Flashscore live-card state with event summary before analysis.

The football live list can lag behind df_sui by one refresh. Downstream LIVE
logic must never evaluate a stale score/clock, keep a stale halftime flag after
the second half has started, or open a fresh signal on the same minute as a
confirmed goal.
"""
from __future__ import annotations

import logging
import re

import unified_bot
from live_engine import fetch_summary

logger = logging.getLogger("score_sync_patch")
_orig_discover = unified_bot.discover_live_matches
_orig_send_signal = unified_bot.telegram_send_signal


def _summary_state(body: str) -> tuple[tuple[int, int] | None, int | None]:
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
        score_changed = new_home > prev_home or new_away > prev_away
        home = max(home, new_home)
        away = max(away, new_away)

        if score_changed:
            mm = re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:\+(\d{1,2}))?", chunk)
            if mm:
                minute = int(mm.group(1)) + int(mm.group(2) or 0)
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

        match.summary_last_goal_minute = last_goal_minute
        match.summary_goal_ahead = False

        if score:
            sh, sa = score
            old_total = int(match.home_score) + int(match.away_score)
            new_total = sh + sa
            if new_total > old_total:
                old = f"{match.home_score}:{match.away_score}"
                match.home_score, match.away_score = sh, sa
                match.summary_goal_ahead = True
                logger.warning("STALE_SCORE_FIXED %s %s — %s | %s -> %d:%d | last_goal=%s", match.event_id, match.home, match.away, old, sh, sa, last_goal_minute if last_goal_minute is not None else "?")

        if last_goal_minute is not None and int(match.minute) < last_goal_minute:
            old_minute = int(match.minute)
            match.minute = last_goal_minute
            logger.warning("STALE_MINUTE_FIXED %s %s — %s | %d' -> %d' due to confirmed goal", match.event_id, match.home, match.away, old_minute, match.minute)

        if bool(getattr(match, "is_halftime", False)) and (int(match.minute) > 45 or (last_goal_minute is not None and last_goal_minute > 45)):
            match.is_halftime = False
            logger.warning("STALE_HALFTIME_FIXED %s %s — %s | live minute=%d last_goal=%s", match.event_id, match.home, match.away, int(match.minute), last_goal_minute if last_goal_minute is not None else "?")

        if last_goal_minute is None:
            match.minutes_since_confirmed_goal = None
            match.recent_confirmed_goal = False
        else:
            since = max(0, int(match.minute) - int(last_goal_minute))
            match.minutes_since_confirmed_goal = since
            match.recent_confirmed_goal = since < 3

    return matches


def _send_synced(match, pressure, recs, text):
    recent = bool(getattr(match, "recent_confirmed_goal", False))
    goal_success = "СИГНАЛ ЗАШЁЛ" in str(text) or "ГОЛ — СИГНАЛ СРАБОТАЛ" in str(text) or "ГОЛ ЗАФИКСИРОВАН" in str(text)
    if recent and not goal_success:
        logger.warning("RECENT_GOAL_SIGNAL_BLOCKED %s %s — %s | minute=%s last_goal=%s since=%s", getattr(match, "event_id", "?"), getattr(match, "home", "?"), getattr(match, "away", "?"), getattr(match, "minute", "?"), getattr(match, "summary_last_goal_minute", "?"), getattr(match, "minutes_since_confirmed_goal", "?"))
        return False
    return _orig_send_signal(match, pressure, recs, text)


unified_bot.discover_live_matches = _discover_synced
unified_bot.telegram_send_signal = _send_synced
