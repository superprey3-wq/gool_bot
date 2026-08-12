"""Multi-logic LIVE candidate gate for persistent hosting.

Every discovered LIVE match is evaluated by all available algorithms:
1) MOMENTUM: short-window pressure / acceleration.
2) DOMINATION: accumulated current-match activity.
3) HISTORY+CURRENT: recent form and H2H combined with the current match.

No match is skipped merely because one route is weak. Missing statistics are
represented explicitly in diagnostics; history is cached per event to keep the
60-second loop lightweight.
"""
from __future__ import annotations

import logging
import time

import unified_bot
from live_engine import (
    StatsSnapshot,
    calculate_goal_pressure,
    fetch_stats,
    fetch_summary,
    get_previous_values,
    parse_goal_timeline,
    parse_stats,
    save_snapshot,
)
from match_history import analyse_history, fetch_match_history

logger = logging.getLogger("live_candidate_patch")

_HISTORY_CACHE: dict[str, tuple[float, float, dict]] = {}
_HISTORY_CACHE_SECONDS = 15 * 60


def _pair_total(stats, key: str) -> float:
    a, b = stats.get(key, (0.0, 0.0))
    return float(a) + float(b)


def _domination_score(match, stats) -> float:
    """Rate accumulated match activity without requiring short-window momentum."""
    minute = max(1, int(match.minute or 1))
    goals = int(match.home_score) + int(match.away_score)
    shots = _pair_total(stats, "shots")
    sot = _pair_total(stats, "shots_on_target")
    xg = _pair_total(stats, "xg")
    big = _pair_total(stats, "big_chances")
    corners = _pair_total(stats, "corners")
    inside = _pair_total(stats, "shots_inside_box")
    touches = _pair_total(stats, "touches_box")

    # 10 shots at 35' means much more than the same volume at 82'.
    pace = min(1.45, 45.0 / minute) if minute <= 45 else min(1.25, 90.0 / minute)

    score = 0.0
    score += min(25.0, shots * pace / 10.0 * 25.0)
    score += min(25.0, sot * pace / 5.0 * 25.0)
    score += min(18.0, xg * pace / 1.20 * 18.0)
    score += min(12.0, goals / 2.0 * 12.0)
    score += min(8.0, corners * pace / 5.0 * 8.0)
    score += min(7.0, big * pace / 2.0 * 7.0)
    score += min(5.0, (inside * 0.22 + touches * 0.08) * pace)
    return round(min(100.0, score), 1)


def _history_score(match) -> tuple[float, dict]:
    """Return goal-profile score from recent form + H2H, cached per event."""
    now = time.time()
    cached = _HISTORY_CACHE.get(match.event_id)
    if cached and now - cached[0] < _HISTORY_CACHE_SECONDS:
        return cached[1], cached[2]

    try:
        ctx = fetch_match_history(match.event_id, match.home, match.away, limit=5)
        analysis = analyse_history(ctx)
    except Exception as exc:
        logger.info("HISTORY %s | unavailable: %s", match.event_id, exc)
        _HISTORY_CACHE[match.event_id] = (now, 0.0, {})
        return 0.0, {}

    samples = [analysis.get("home", {}), analysis.get("away", {}), analysis.get("h2h", {})]
    valid = [s for s in samples if s.get("n", 0)]
    if not valid:
        _HISTORY_CACHE[match.event_id] = (now, 0.0, analysis)
        return 0.0, analysis

    avg_total = float(analysis.get("historical_avg_total", 0.0) or 0.0)
    over25 = sum(float(s.get("over25", 0.0) or 0.0) for s in valid) / len(valid)
    over35 = sum(float(s.get("over35", 0.0) or 0.0) for s in valid) / len(valid)
    over45 = sum(float(s.get("over45", 0.0) or 0.0) for s in valid) / len(valid)

    score = min(45.0, avg_total / 4.0 * 45.0)
    score += over25 * 25.0
    score += over35 * 18.0
    score += over45 * 12.0
    score = round(min(100.0, score), 1)
    _HISTORY_CACHE[match.event_id] = (now, score, analysis)
    return score, analysis


def _candidate(match, stats, pressure) -> tuple[bool, str, float, float, float]:
    """Evaluate every match through every scoring route."""
    domination = _domination_score(match, stats)
    history, _ = _history_score(match)

    momentum_path = pressure.score >= unified_bot.LIVE_SIGNAL_THRESHOLD
    domination_path = domination >= 72.0

    # History can confirm an already-active current match but never create a
    # signal from historical results alone.
    history_path = domination >= 54.0 and history >= 62.0

    # Extra route for very active first halves: catches games like 1:2 around
    # 35-42' where the accumulated picture is strong even if the 8-min delta is quiet.
    first_half_activity = (
        match.minute <= 45
        and not match.is_halftime
        and _pair_total(stats, "shots") >= 10
        and _pair_total(stats, "shots_on_target") >= 5
        and (int(match.home_score) + int(match.away_score)) >= 2
        and domination >= 64.0
    )

    combined = round(
        min(100.0, pressure.score * 0.38 + domination * 0.44 + history * 0.18),
        1,
    )

    routes = []
    if momentum_path:
        routes.append("MOMENTUM")
    if domination_path:
        routes.append("DOMINATION")
    if history_path:
        routes.append("HISTORY+CURRENT")
    if first_half_activity:
        routes.append("ACTIVE-1H")

    return bool(routes), "+".join(routes) if routes else "REJECT", combined, domination, history


async def scan_live_once_multi():
    live = await unified_bot.discover_live_matches()
    logger.info("Найдено LIVE-матчей: %d | каждый матч -> MOMENTUM+DOMINATION+HISTORY", len(live))
    state = unified_bot._load_sent()
    sent = 0
    live_ids = {m.event_id for m in live}

    for key in list(state):
        if key.startswith("TRACK:") and key.split(":", 1)[1] not in live_ids:
            state.pop(key, None)

    for match in live:
        # Never skip a discovered match before scoring. If detailed stats are
        # unavailable, use an empty snapshot so all algorithms still run and
        # diagnostics clearly show the missing-data case.
        body = fetch_stats(match.event_id)
        stats = parse_stats(body) if body else {}
        stats_status = "OK" if stats else ("NO_BODY" if not body else "NOT_PARSED")

        previous = get_previous_values(match.event_id, match.minute, 8) if stats else None
        pressure = calculate_goal_pressure(match, stats, previous)
        if stats:
            save_snapshot(match.event_id, StatsSnapshot(int(time.time()), match.minute, stats))
        goal_times = parse_goal_timeline(fetch_summary(match.event_id))

        qualifies, route, combined, domination, history = _candidate(match, stats, pressure)
        shots = _pair_total(stats, "shots")
        sot = _pair_total(stats, "shots_on_target")
        xg = _pair_total(stats, "xg")
        logger.info(
            "LIVE_EVAL %d' %s — %s %d:%d | stats=%s | "
            "momentum=%.1f pressure=%.1f domination=%.1f history=%.1f total=%.1f | "
            "shots=%.0f sot=%.0f xG=%.2f | %s %s",
            match.minute,
            match.home,
            match.away,
            match.home_score,
            match.away_score,
            stats_status,
            pressure.momentum,
            pressure.score,
            domination,
            history,
            combined,
            shots,
            sot,
            xg,
            "✅" if qualifies else "❌",
            route,
        )

        now = time.time()
        track_key = f"TRACK:{match.event_id}"
        tracked = state.get(track_key)
        current_score = f"{match.home_score}:{match.away_score}"

        if not tracked:
            if not qualifies:
                continue
            pressure.reasons.insert(0, f"Сценарий отбора: {route}")
            recs = unified_bot._recommendations(
                unified_bot._fetch_event_odds(match.event_id), match, pressure
            )
            if unified_bot.telegram_send(
                unified_bot._format_signal(match, pressure, stats, recs, goal_times, "signal")
            ):
                unified_bot._record_live(match, pressure, stats, recs, "signal")
                state[track_key] = {
                    "tracked_since": now,
                    "ts": now,
                    "score": current_score,
                    "minute": match.minute,
                    "pressure": pressure.score,
                    "candidate_score": combined,
                    "route": route,
                    "halftime_sent": match.is_halftime,
                }
                sent += 1
            continue

        previous_score = str(tracked.get("score", current_score))
        score_changed = previous_score != current_score
        halftime_new = match.is_halftime and not bool(tracked.get("halftime_sent"))
        last_ts = float(tracked.get("ts", 0))
        last_pressure = float(tracked.get("pressure", 0))
        last_candidate = float(tracked.get("candidate_score", 0))
        pressure_jump = (
            pressure.score >= unified_bot.LIVE_SIGNAL_THRESHOLD
            and pressure.score >= last_pressure + 8
        )
        candidate_jump = qualifies and combined >= last_candidate + 10
        regular_followup = (
            qualifies and now - last_ts >= unified_bot.LIVE_COOLDOWN_MINUTES * 60
        )

        if score_changed or halftime_new or pressure_jump or candidate_jump or regular_followup:
            reason = "goal" if score_changed else "followup"
            if qualifies:
                pressure.reasons.insert(0, f"Сценарий отбора: {route}")
            recs = unified_bot._recommendations(
                unified_bot._fetch_event_odds(match.event_id), match, pressure
            )
            if unified_bot.telegram_send(
                unified_bot._format_signal(match, pressure, stats, recs, goal_times, reason)
            ):
                unified_bot._record_live(match, pressure, stats, recs, reason)
                tracked.update(
                    {
                        "ts": now,
                        "score": current_score,
                        "minute": match.minute,
                        "pressure": pressure.score,
                        "candidate_score": combined,
                        "route": route,
                        "halftime_sent": bool(tracked.get("halftime_sent"))
                        or match.is_halftime,
                    }
                )
                state[track_key] = tracked
                sent += 1
        else:
            tracked.update(
                {
                    "score": current_score,
                    "minute": match.minute,
                    "candidate_score": combined,
                    "route": route,
                }
            )
            state[track_key] = tracked

    unified_bot._save_sent(state)
    logger.info(
        "Отправлено LIVE-сигналов/обновлений: %d; сопровождается матчей: %d",
        sent,
        sum(1 for k in state if k.startswith("TRACK:")),
    )
    return sent


unified_bot.scan_live_once = scan_live_once_multi
