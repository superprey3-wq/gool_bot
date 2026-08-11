"""Run unified bot with full master-feed discovery and verified LIVE-only odds."""
from __future__ import annotations

import asyncio
import statistics
import unified_bot
from feed_live_discovery import discover_live_matches as discover_all_live_matches
from live_odds import fetch_live_odds
from match_history import analyse_history, fetch_match_history


# Built only when a signal/update is actually being prepared; LIVE scan of every
# event does not fetch H2H/history.
_SIGNAL_INSIGHTS: dict[str, str] = {}
_SMART_BLOCK_TOKEN = "__SMART_LIVE_BET_BLOCK__"


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
    if scope == "SECOND_HALF":
        return 0
    return match.home_score + match.away_score


def _median_over_prices(entries, scope: str) -> dict[float, tuple[float, int]]:
    buckets: dict[float, list[float]] = {}
    for entry in entries:
        if entry.get("bettingType") != "OVER_UNDER" or entry.get("bettingScope") != scope:
            continue
        for item in entry.get("odds") or []:
            if str(item.get("selection", "")).upper() != "OVER" or item.get("active") is False:
                continue
            try:
                line = float((item.get("handicap") or {}).get("value"))
                odd = float(item.get("value"))
            except (TypeError, ValueError, AttributeError):
                continue
            if odd > 1.0:
                buckets.setdefault(line, []).append(odd)
    return {line: (float(statistics.median(vals)), len(vals)) for line, vals in buckets.items() if vals}


def _rate_over(rows, line: float) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if row.total > line) / len(rows)


def _weighted_history_rate(ctx, line: float) -> float | None:
    values: list[tuple[float, float]] = []
    for rows, weight in ((ctx.home_recent, 1.0), (ctx.away_recent, 1.0), (ctx.h2h, 0.7)):
        rate = _rate_over(rows, line)
        if rate is not None:
            values.append((rate, weight))
    if not values:
        return None
    return sum(v * w for v, w in values) / sum(w for _, w in values)


def _next_goal_1h(entries, match) -> str:
    if match.minute > 45 or match.is_halftime:
        return ""
    prices = _median_over_prices(entries, "FIRST_HALF")
    target = match.home_score + match.away_score + 0.5
    found = prices.get(target)
    if not found:
        return (
            "⚽ <b>ЕЩЁ 1 ГОЛ В 1-М ТАЙМЕ</b>\n"
            "Текущий LIVE-коэффициент сейчас недоступен."
        )
    odd, books = found
    return (
        "⚽ <b>ЕЩЁ 1 ГОЛ В 1-М ТАЙМЕ</b>\n"
        f"ТБ {target:g} 1Т — LIVE-кэф <b>{odd:.2f}</b> · {books} БК"
    )


def _history_summary(match, ctx, analysis) -> str:
    parts = []
    for label, stats in ((match.home, analysis["home"]), (match.away, analysis["away"])):
        if stats["n"]:
            parts.append(
                f"{label}: ТБ2.5 {round(stats['over25'] * 100):d}% из {int(stats['n'])}, "
                f"ср. тотал {stats['avg_total']:.2f}"
            )
    h2h = analysis["h2h"]
    if h2h["n"]:
        parts.append(
            f"H2H: ТБ2.5 {round(h2h['over25'] * 100):d}% из {int(h2h['n'])}, "
            f"ср. тотал {h2h['avg_total']:.2f}"
        )
    if not parts:
        return "История Flashscore для этого матча недоступна — решение основано на LIVE-статистике."
    return "\n".join(f"• {x}" for x in parts)


def _model_pick(entries, match, pressure, ctx, analysis) -> str:
    prices = _median_over_prices(entries, "FULL_TIME")
    if not prices:
        return (
            "🧠 <b>МОЯ СТАВКА НА МАТЧ</b>\n"
            "Не публикую ставку: подтверждённого LIVE-коэффициента на общий тотал сейчас нет."
        )

    goals = match.home_score + match.away_score
    hist_avg = float(analysis.get("historical_avg_total") or 0.0)
    if hist_avg <= 0:
        hist_avg = max(2.4, float(goals))
    remaining = max(0.0, 90.0 - float(match.minute)) / 90.0
    pressure_factor = 0.65 + min(1.0, pressure.score / 100.0) * 0.70
    projected_final = goals + hist_avg * remaining * pressure_factor

    candidates = []
    for line, (odd, books) in prices.items():
        if line <= goals or odd < 1.10 or odd > 5.0:
            continue
        hist_rate = _weighted_history_rate(ctx, line)
        hist_component = 0.50 if hist_rate is None else hist_rate
        margin = projected_final - line
        late_penalty = 10 if match.minute >= 80 else 5 if match.minute >= 75 else 0
        confidence = 44 + pressure.score * 0.28 + hist_component * 20 + max(-10, min(10, margin * 7)) - late_penalty
        confidence = max(35, min(91, round(confidence)))
        # Prefer a meaningful but not extreme current price and a line that the
        # projection clears by at least a little.
        utility = confidence - abs(odd - 1.90) * 7 + max(-6, min(6, margin * 4))
        candidates.append((utility, line, odd, books, confidence, hist_rate, margin))

    if not candidates:
        return (
            "🧠 <b>МОЯ СТАВКА НА МАТЧ</b>\n"
            "Сейчас нет подходящего подтверждённого LIVE-тотала для входа."
        )

    candidates.sort(reverse=True)
    _, line, odd, books, confidence, hist_rate, margin = candidates[0]
    support = ""
    if hist_rate is not None:
        support = f" · исторический проход линии {round(hist_rate * 100):d}%"
    return (
        "🧠 <b>МОЯ СТАВКА НА МАТЧ</b>\n"
        f"ТБ {line:g} — LIVE-кэф <b>{odd:.2f}</b> · модель <b>{confidence}%</b> · {books} БК{support}\n"
        f"Проекция модели по текущему темпу: около <b>{projected_final:.1f}</b> гола к финалу."
    )


def _build_insight(entries, match, pressure) -> str:
    ctx = fetch_match_history(match.event_id, match.home, match.away, limit=5)
    analysis = analyse_history(ctx)
    blocks = []
    next_goal = _next_goal_1h(entries, match)
    if next_goal:
        blocks.append(next_goal)
    blocks.append(_model_pick(entries, match, pressure, ctx, analysis))
    blocks.append("📚 <b>ФОРМА И ОЧНЫЕ ВСТРЕЧИ</b>\n" + _history_summary(match, ctx, analysis))
    return "\n\n".join(blocks)


def _recommendations(entries, match, pressure):
    """Keep raw recommendation rows for journal, but build one clear user pick."""
    if match.minute <= 45 and not match.is_halftime:
        recs = (
            unified_bot._collect_scope_recommendations(entries, match, pressure, "FIRST_HALF")
            + unified_bot._collect_scope_recommendations(entries, match, pressure, "FULL_TIME")
        )
    else:
        recs = (
            unified_bot._collect_scope_recommendations(entries, match, pressure, "SECOND_HALF")
            + unified_bot._collect_scope_recommendations(entries, match, pressure, "FULL_TIME")
        )
    try:
        _SIGNAL_INSIGHTS[match.event_id] = _build_insight(entries, match, pressure)
    except Exception:
        _SIGNAL_INSIGHTS[match.event_id] = (
            "🧠 <b>МОЯ СТАВКА НА МАТЧ</b>\n"
            "Дополнительный анализ формы временно недоступен; LIVE-сигнал сохранён."
        )
    return recs


def _format_bets(recs):
    # Original formatter has no match/event context. The token is replaced below
    # by the event-aware block built in _recommendations().
    return _SMART_BLOCK_TOKEN


_original_format_signal = unified_bot._format_signal


def _format_signal(*args, **kwargs):
    match = args[0] if args else kwargs.get("match")
    text = _original_format_signal(*args, **kwargs)
    insight = _SIGNAL_INSIGHTS.get(getattr(match, "event_id", ""), "LIVE-анализ ставки временно недоступен.")
    text = text.replace(_SMART_BLOCK_TOKEN, insight)
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
