"""GOOL XG secondary analysis layer.

Built only from data that GOOL BOT already receives reliably enough to use:
- StrengthXG: recent-history Elo/Poisson forecast from market_math_patch;
- MarketXG: remaining-goal expectation inferred from current LIVE total price;
- CalcXG: GOOL's own shot-quality proxy from shots/SOT/big chances/box activity.

Missing sources never become zero and never reject a match. One available source is
information-only. Two or three sources may slightly adjust MASTER, but this layer
can never create ENTRY/STRONG on its own. A rejected setup may only be exposed as
OBSERVE when the existing GOOL engine is already close and the secondary models agree.
"""
from __future__ import annotations

import logging
import math
import statistics
import time

import live_candidate_patch as lc
import market_math_patch as mm

logger = logging.getLogger("gool_xg_consensus")

_orig_evaluate = lc._evaluate
_orig_format = lc._format_strategy_signal
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_SECONDS = 300

CORE_WEIGHTS = {"strength": 0.40, "market": 0.35, "calc": 0.25}
MIN_MINUTE_FOR_INFLUENCE = 10


def _total(stats: dict, key: str) -> float:
    try:
        a, b = stats.get(key, (0.0, 0.0))
        return max(0.0, float(a)) + max(0.0, float(b))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _remaining_minutes(match) -> float:
    if getattr(match, "is_halftime", False):
        return 49.0
    minute = max(0.0, float(getattr(match, "minute", 0) or 0))
    return max(0.0, 94.0 - minute)


def _elapsed_minutes(match) -> float:
    if getattr(match, "is_halftime", False):
        return 45.0
    return max(10.0, min(94.0, float(getattr(match, "minute", 0) or 0)))


def _pace_remaining(cumulative: float, match, damp: float) -> float | None:
    if cumulative <= 0:
        return None
    elapsed = _elapsed_minutes(match)
    remaining = _remaining_minutes(match)
    if remaining <= 0:
        return 0.0
    value = cumulative / elapsed * remaining * damp
    return round(max(0.02, min(3.50, value)), 3)


def _strength_xg(match) -> float | None:
    fc = mm._math_forecast(match)
    if not fc:
        return None
    total = float(fc.get("xg_total", 0) or 0)
    if total <= 0:
        return None
    remaining = _remaining_minutes(match)
    phase = 1.08 if float(getattr(match, "minute", 0) or 0) >= 60 else 1.0
    return round(max(0.02, min(3.50, total * (remaining / 94.0) * phase)), 3)


def _lambda_for_at_least_two(prob: float) -> float:
    lo, hi = 0.0, 8.0
    for _ in range(48):
        mid = (lo + hi) / 2.0
        p = 1.0 - math.exp(-mid) * (1.0 + mid)
        if p < prob:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _market_xg(market: dict) -> float | None:
    if not market or not market.get("available"):
        return None
    try:
        prob = float(market.get("market_probability", 0) or 0) / 100.0
        step = int(market.get("goal_step", 1) or 1)
    except (TypeError, ValueError):
        return None
    prob = max(0.02, min(0.96, prob))
    lam = -math.log(1.0 - prob) if step <= 1 else _lambda_for_at_least_two(prob)
    return round(max(0.02, min(3.50, lam)), 3)


def _calculated_xg_total(stats: dict) -> float:
    shots = _total(stats, "shots")
    sot = _total(stats, "shots_on_target")
    big = _total(stats, "big_chances")
    inside = _total(stats, "shots_inside_box")
    touches = _total(stats, "touches_box")
    corners = _total(stats, "corners")
    if shots + sot + big + inside + touches + corners <= 0:
        return 0.0
    value = (
        0.028 * shots
        + 0.105 * sot
        + 0.260 * big
        + 0.022 * inside
        + 0.007 * touches
        + 0.012 * corners
    )
    return max(0.0, min(6.0, value))


def _calculated_xg(stats: dict, match) -> float | None:
    return _pace_remaining(_calculated_xg_total(stats), match, 0.78)


def _agreement(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    spread = statistics.mean(abs(v - med) for v in values) / max(0.25, med)
    return round(max(0.0, min(100.0, 100.0 - spread * 120.0)), 1)


def _consensus(match, stats: dict, market: dict) -> dict:
    components = {
        "strength": _strength_xg(match),
        "market": _market_xg(market),
        "calc": _calculated_xg(stats, match),
    }
    available = {k: v for k, v in components.items() if v is not None}
    missing = [k for k in CORE_WEIGHTS if components.get(k) is None]

    if not available:
        result = {
            "components": components,
            "sources": 0,
            "missing": missing,
            "lambda": 0.0,
            "goal_probability": 0.0,
            "agreement": 0.0,
            "score": 0.0,
            "reliability": "NONE",
        }
    else:
        denom = sum(CORE_WEIGHTS[k] for k in available) or 1.0
        lam = sum(float(v) * CORE_WEIGHTS[k] for k, v in available.items()) / denom
        agree = _agreement([float(v) for v in available.values()])
        goal_p = (1.0 - math.exp(-max(0.0, lam))) * 100.0
        sources = len(available)
        source_factor = {1: 0.72, 2: 0.90, 3: 1.00}.get(sources, 1.0)
        agreement_factor = 0.92 + 0.08 * (agree / 100.0 if sources >= 2 else 0.0)
        score = max(0.0, min(100.0, goal_p * source_factor * agreement_factor))
        result = {
            "components": components,
            "sources": sources,
            "missing": missing,
            "lambda": round(lam, 3),
            "goal_probability": round(goal_p, 1),
            "agreement": agree,
            "score": round(score, 1),
            "reliability": "FULL" if sources == 3 else "PARTIAL" if sources == 2 else "INFO_ONLY",
        }

    _CACHE[str(getattr(match, "event_id", ""))] = (time.time(), result)
    return result


def _bonus(model: dict, minute: int) -> float:
    if minute < MIN_MINUTE_FOR_INFLUENCE:
        return 0.0
    score = float(model.get("score", 0) or 0)
    agree = float(model.get("agreement", 0) or 0)
    sources = int(model.get("sources", 0) or 0)
    if sources >= 3 and agree >= 60 and score >= 75:
        return 4.0
    if sources >= 2 and agree >= 55 and score >= 65:
        return 2.0
    if sources >= 2 and score <= 35:
        return -2.0
    if sources >= 2 and score <= 45:
        return -1.0
    return 0.0


def _evaluate(match, stats, pressure, goals, market):
    qualifies, route, master, scores, hazards, market = _orig_evaluate(match, stats, pressure, goals, market)
    model = _consensus(match, stats, market)
    scores["XG_CONSENSUS"] = float(model.get("score", 0) or 0)

    minute = int(getattr(match, "minute", 0) or 0)
    bonus = _bonus(model, minute)
    master = max(0.0, min(100.0, master + bonus))

    if not qualifies:
        observe_rescue = (
            minute >= MIN_MINUTE_FOR_INFLUENCE
            and minute <= lc.MAX_NEW_SIGNAL_MINUTE
            and master >= lc.OBSERVE_MIN_SCORE
            and int(model.get("sources", 0) or 0) >= 2
            and float(model.get("score", 0) or 0) >= 64
            and float(model.get("agreement", 0) or 0) >= 60
        )
        if observe_rescue:
            qualifies = True
            route = "XG_CONSENSUS_OBSERVE"
            master = min(master, lc.ENTRY_MIN_SCORE - 1.0)

    c = model.get("components") or {}
    logger.info(
        "GOOL_XG %d' %s — %s | strength=%s market=%s calc=%s | lambda=%.2f pGoal=%.0f%% agree=%.0f%% sources=%d reliability=%s missing=%s score=%.0f bonus=%+.0f | %s",
        minute,
        getattr(match, "home", ""), getattr(match, "away", ""),
        c.get("strength"), c.get("market"), c.get("calc"),
        float(model.get("lambda", 0) or 0), float(model.get("goal_probability", 0) or 0),
        float(model.get("agreement", 0) or 0), int(model.get("sources", 0) or 0),
        model.get("reliability", "NONE"), ",".join(model.get("missing") or []) or "none",
        float(model.get("score", 0) or 0), bonus,
        "OBSERVE_RESCUE" if route == "XG_CONSENSUS_OBSERVE" else "NORMAL",
    )
    return qualifies, route, master, scores, hazards, market


def _fmt(v) -> str:
    return "—" if v is None else f"{float(v):.2f}"


def _cached(match) -> dict | None:
    item = _CACHE.get(str(getattr(match, "event_id", "")))
    if not item or time.time() - item[0] > _CACHE_SECONDS:
        return None
    return item[1]


def _format_strategy_signal(match, pressure, stats, recs, goals, reason, route, master, hazards, market):
    text = _orig_format(match, pressure, stats, recs, goals, reason, route, master, hazards, market)
    model = _cached(match) or _consensus(match, stats, market)
    c = model.get("components") or {}
    pieces = []
    if c.get("strength") is not None:
        pieces.append(f"Strength {_fmt(c.get('strength'))}")
    if c.get("market") is not None:
        pieces.append(f"Market {_fmt(c.get('market'))}")
    if c.get("calc") is not None:
        pieces.append(f"Calc {_fmt(c.get('calc'))}")

    line1 = "🎯 GOOL XG: " + (" · ".join(pieces) if pieces else "нет доступных источников")
    line2 = (
        f"🤝 Consensus: <b>{float(model.get('lambda', 0)):.2f}</b> ож. гола · "
        f"ещё гол <b>{float(model.get('goal_probability', 0)):.0f}%</b> · "
        f"источников {int(model.get('sources', 0))}/3 · {model.get('reliability', 'NONE')}"
    )

    marker = "\n🧠 Рейтинг сигнала:"
    block = f"\n{line1}\n{line2}"
    if marker in text:
        return text.replace(marker, block + marker)
    return text + block


lc._evaluate = _evaluate
lc._format_strategy_signal = _format_strategy_signal
