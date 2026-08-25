"""Run unified bot with full master-feed discovery and verified LIVE-only odds."""
from __future__ import annotations

import asyncio
import statistics
import unified_bot
from feed_live_discovery import discover_live_matches as discover_all_live_matches
from live_odds import fetch_live_odds
from match_history import analyse_history, fetch_match_history

_SIGNAL_INSIGHTS: dict[str, str] = {}
_SMART_BLOCK_TOKEN = "__SMART_LIVE_BET_BLOCK__"


async def discover_live_matches():
    """Return the full LIVE feed for all strategy windows."""
    return await discover_all_live_matches()


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
            "⚽ <b>СЦЕНАРИЙ ДО ПЕРЕРЫВА</b>\n"
            "Линия на ещё один гол в 1-м тайме сейчас не подтверждена рынком."
        )
    odd, books = found
    return (
        "⚽ <b>СЦЕНАРИЙ ДО ПЕРЕРЫВА</b>\n"
        f"Ещё 1 гол: ТБ {target:g} 1Т · LIVE <b>{odd:.2f}</b> · источников {books}."
    )


def _history_summary(match, ctx, analysis) -> str:
    parts = []
    total_n = 0
    for label, stats in ((match.home, analysis["home"]), (match.away, analysis["away"])):
        if stats["n"]:
            total_n += int(stats["n"])
            parts.append(
                f"{label}: ТБ2.5 {round(stats['over25'] * 100):d}% / {int(stats['n'])}, "
                f"ср. тотал {stats['avg_total']:.2f}"
            )
    h2h = analysis["h2h"]
    if h2h["n"]:
        total_n += int(h2h["n"])
        parts.append(
            f"H2H: ТБ2.5 {round(h2h['over25'] * 100):d}% / {int(h2h['n'])}, "
            f"ср. тотал {h2h['avg_total']:.2f}"
        )
    if not parts:
        return "История недоступна — решение строится на LIVE-данных и рынке."
    note = "История используется как слабая поправка, а не как основной сигнал."
    if total_n < 8:
        note = "Выборка истории маленькая — её вес в модели минимальный."
    return "\n".join(f"• {x}" for x in parts) + f"\n<i>{note}</i>"


def _edge_label(edge: float) -> str:
    pp = edge * 100
    if pp >= 5:
        return f"плюс к рынку <b>+{pp:.1f} п.п.</b>"
    if pp >= 2:
        return f"небольшой плюс <b>+{pp:.1f} п.п.</b>"
    if pp > -2:
        return f"почти по рынку <b>{pp:+.1f} п.п.</b>"
    return f"ниже рынка <b>{pp:.1f} п.п.</b>"


def _model_pick(entries, match, pressure, ctx, analysis) -> str:
    prices = _median_over_prices(entries, "FULL_TIME")
    goals = match.home_score + match.away_score
    if not prices:
        p = unified_bot._live_over_probability(pressure.score, pressure.momentum, goals + 0.5, goals, "FULL_TIME", match.minute, None)
        fair = 1.0 / max(p, 0.01)
        return (
            "🎯 <b>ОСНОВНОЙ LIVE-СЦЕНАРИЙ</b>\n"
            f"Ещё 1 гол до конца матча: модель <b>{round(p * 100)}%</b> · честный кэф ≈ <b>{fair:.2f}</b>.\n"
            "Рыночной котировки нет — вход без подтверждения коэффициентом не считаем полноценным."
        )

    candidates = []
    for line, (odd, books) in prices.items():
        if line <= goals or odd < 1.10 or odd > 8.0:
            continue
        live_p = unified_bot._live_over_probability(pressure.score, pressure.momentum, line, goals, "FULL_TIME", match.minute, odd)
        hist_rate = _weighted_history_rate(ctx, line)
        if hist_rate is not None:
            hist_weight = 0.04 if match.minute >= 80 else 0.08 if match.minute >= 70 else 0.15
            calibrated_p = live_p * (1.0 - hist_weight) + hist_rate * hist_weight
        else:
            calibrated_p = live_p
        calibrated_p = max(0.01, min(0.94, calibrated_p))
        confidence = round(calibrated_p * 100)
        market_p = min(0.95, 1.0 / odd)
        edge = calibrated_p - market_p
        needed = unified_bot._goals_needed_for_over(line, goals)
        utility = confidence + edge * 80 - abs(odd - 1.90) * 3 - max(0, needed - 1) * 4
        candidates.append((utility, line, odd, books, confidence, hist_rate, edge, needed, calibrated_p))

    if not candidates:
        p = unified_bot._live_over_probability(pressure.score, pressure.momentum, goals + 0.5, goals, "FULL_TIME", match.minute, None)
        return (
            "🎯 <b>ОСНОВНОЙ LIVE-СЦЕНАРИЙ</b>\n"
            f"Ещё 1 гол: модель <b>{round(p * 100)}%</b>.\n"
            "Доступные линии сейчас не дают нормального сочетания вероятности и цены — лучше пропуск."
        )

    candidates.sort(reverse=True)
    _, line, odd, books, confidence, hist_rate, edge, needed, calibrated_p = candidates[0]
    fair = 1.0 / calibrated_p
    history = f" · история линии {round(hist_rate * 100):d}%" if hist_rate is not None else ""
    action = "✅ Цена интересная" if edge >= 0.03 else "🟡 Цена пограничная" if edge >= 0 else "⛔ Цена хуже оценки модели"
    return (
        "🎯 <b>ОСНОВНОЙ LIVE-СЦЕНАРИЙ</b>\n"
        f"ТБ {line:g} · LIVE <b>{odd:.2f}</b> · модель <b>{confidence}%</b> · честный кэф ≈ <b>{fair:.2f}</b>\n"
        f"{action}: {_edge_label(edge)} · источников {books}{history}.\n"
        f"Нужно ещё голов: <b>{needed}</b>. Вес LIVE-давления и рынка выше, чем исторической формы."
    )


def _build_insight(entries, match, pressure) -> str:
    ctx = fetch_match_history(match.event_id, match.home, match.away, limit=5)
    analysis = analyse_history(ctx)
    blocks = [
        "📈 <b>СОСТОЯНИЕ МАТЧА</b>\n"
        f"Давление <b>{pressure.score:.0f}/100</b> · импульс <b>{pressure.momentum:.0f}/100</b>. "
        "Модель пересчитывает вероятность по времени, счёту, текущему давлению и LIVE-цене."
    ]
    next_goal = _next_goal_1h(entries, match)
    if next_goal:
        blocks.append(next_goal)
    blocks.append(_model_pick(entries, match, pressure, ctx, analysis))
    blocks.append("📚 <b>ФОРМА / H2H</b>\n" + _history_summary(match, ctx, analysis))
    return "\n\n".join(blocks)


def _recommendations(entries, match, pressure):
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
            "🎯 <b>ОСНОВНОЙ LIVE-СЦЕНАРИЙ</b>\n"
            "Расширенный анализ формы временно недоступен; LIVE-сигнал оставлен только на данных матча и рынка."
        )
    return recs


def _format_bets(recs):
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


unified_bot.discover_live_matches = discover_live_matches
unified_bot._fetch_event_odds = fetch_live_odds
unified_bot._scope_current_goals = _scope_current_goals
unified_bot._recommendations = _recommendations
unified_bot._format_bets = _format_bets
unified_bot._format_signal = _format_signal

if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
