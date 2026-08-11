"""Run unified bot with full master-feed discovery and verified LIVE-only odds."""
from __future__ import annotations

import asyncio
import unified_bot
from feed_live_discovery import discover_live_matches as discover_all_live_matches
from live_odds import fetch_live_odds


async def discover_live_matches():
    """Keep tracked matches to FT, but never start monitoring a new match after 85'."""
    matches = await discover_all_live_matches()
    state = unified_bot._load_sent()
    result = []
    for match in matches:
        tracked = f"TRACK:{match.event_id}" in state
        if match.minute <= 85 or tracked:
            result.append(match)
    return result


def _scope_current_goals(match, scope: str) -> int:
    # FIRST_HALF is only requested before HT, so match score equals first-half goals.
    # For SECOND_HALF the live endpoint itself returns only current active cumulative
    # second-half lines. We deliberately do not use total match goals to filter them.
    if scope == "SECOND_HALF":
        return 0
    return match.home_score + match.away_score


def _recommendations(entries, match, pressure):
    """Always pair the current-period LIVE total with the full-match LIVE total."""
    if match.minute <= 45 and not match.is_halftime:
        return (
            unified_bot._collect_scope_recommendations(entries, match, pressure, "FIRST_HALF")
            + unified_bot._collect_scope_recommendations(entries, match, pressure, "FULL_TIME")
        )
    # At HT and throughout the second half show both the 2H market and whole-match market.
    return (
        unified_bot._collect_scope_recommendations(entries, match, pressure, "SECOND_HALF")
        + unified_bot._collect_scope_recommendations(entries, match, pressure, "FULL_TIME")
    )


def _format_bets(recs):
    if not recs:
        return "LIVE-коэффициент на тоталы сейчас недоступен."
    groups = []
    labels = {
        "FIRST_HALF": "🕐 <b>ДО КОНЦА 1-ГО ТАЙМА · LIVE</b>",
        "SECOND_HALF": "🕑 <b>ДО КОНЦА 2-ГО ТАЙМА · LIVE</b>",
        "FULL_TIME": "⚽ <b>ДО КОНЦА МАТЧА · LIVE</b>",
    }
    for scope in ("FIRST_HALF", "SECOND_HALF", "FULL_TIME"):
        rows = [r for r in recs if r["scope"] == scope]
        if not rows:
            continue
        lines = [labels[scope]]
        for r in rows:
            books = f" · {r['bookmakers']} БК" if r.get("bookmakers") else ""
            lines.append(
                f"ТБ {r['line']:g} — LIVE-кэф <b>{r['odd']:.2f}</b> | "
                f"уверенность модели <b>{r['confidence']}%</b>{books}"
            )
        groups.append("\n".join(lines))
    return "\n\n".join(groups) if groups else "LIVE-коэффициент на тоталы сейчас недоступен."


_original_format_signal = unified_bot._format_signal

def _format_signal(*args, **kwargs):
    text = _original_format_signal(*args, **kwargs)
    return text.replace(
        "Коэффициент — медиана активных букмекеров LSApp.",
        "Коэффициенты — текущие LIVE-котировки Flashscore/LSApp на момент сигнала.",
    )


# Replace data sources/policy. Pressure, stats, Telegram and tracking remain unchanged.
unified_bot.discover_live_matches = discover_live_matches
unified_bot._fetch_event_odds = fetch_live_odds
unified_bot._scope_current_goals = _scope_current_goals
unified_bot._recommendations = _recommendations
unified_bot._format_bets = _format_bets
unified_bot._format_signal = _format_signal

if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
