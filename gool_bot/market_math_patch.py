"""Final GOOL LIVE enrichments: Kambi fallback + conservative math context.

Imported after the existing phase/score patches. Kambi only fills missing target
lines. Elo+Poisson is informational and may nudge the displayed rating slightly;
it never turns a rejected LIVE setup into a qualifying signal by itself.
"""
from __future__ import annotations

import logging
import re
import time

import live_candidate_patch as lc
from kambi_live_odds import get_live_goal_totals
from match_history import fetch_match_history
from math_forecast import forecast_from_history

logger = logging.getLogger("market_math_patch")
_orig_market = lc._market
_orig_evaluate = lc._evaluate
_orig_format = lc._format_strategy_signal
_MATH_CACHE: dict[str, tuple[float, dict]] = {}
_MATH_CACHE_SECONDS = 900


def _norm(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split())


def _team_rows(rows, team_name: str):
    team = _norm(team_name)
    out = []
    for row in rows:
        home = _norm(getattr(row, "home", ""))
        away = _norm(getattr(row, "away", ""))
        hg = int(getattr(row, "home_goals", 0) or 0)
        ag = int(getattr(row, "away_goals", 0) or 0)
        if team and (team in home or home in team):
            out.append({"goals_for": hg, "goals_against": ag})
        elif team and (team in away or away in team):
            out.append({"goals_for": ag, "goals_against": hg})
    return out


def _math_forecast(match) -> dict:
    now = time.time()
    cached = _MATH_CACHE.get(match.event_id)
    if cached and now - cached[0] < _MATH_CACHE_SECONDS:
        return cached[1]
    try:
        ctx = fetch_match_history(match.event_id, match.home, match.away, limit=8)
        home_rows = _team_rows(ctx.home_recent, match.home)
        away_rows = _team_rows(ctx.away_recent, match.away)
        if len(home_rows) < 3 or len(away_rows) < 3:
            result = {}
        else:
            result = forecast_from_history(home_rows, away_rows)
    except Exception as exc:
        logger.info("MATH_FORECAST_FAILED %s: %s", match.event_id, exc)
        result = {}
    _MATH_CACHE[match.event_id] = (now, result)
    return result


def _visible(row) -> bool:
    try:
        return float(row.get("odd")) > 1.001
    except (TypeError, ValueError, AttributeError):
        return False


def _enrich_kambi(recs, match, pressure):
    goals = int(match.home_score) + int(match.away_score)
    targets = (goals + 0.5, goals + 1.5)
    needed_scopes = {"FULL_TIME"}
    if match.minute <= 45 and not match.is_halftime:
        needed_scopes.add("FIRST_HALF")

    existing = {(str(r.get("scope")), float(r.get("line", -99))) for r in recs if _visible(r)}
    missing = {(scope, float(line)) for scope in needed_scopes for line in targets if (scope, float(line)) not in existing}
    if not missing:
        return recs

    try:
        kambi = get_live_goal_totals(match.home, match.away)
    except Exception as exc:
        logger.info("KAMBI_ENRICH_FAILED %s: %s", match.event_id, exc)
        return recs

    added = []
    for row in kambi:
        key = (str(row.get("scope")), float(row.get("line", -99)))
        if key not in missing or not _visible(row):
            continue
        copy = dict(row)
        if copy["scope"] == "FULL_TIME":
            odd = float(copy["odd"])
            conf = lc.unified_bot._model_confidence(
                pressure.score, pressure.momentum, float(copy["line"]), goals,
                "FULL_TIME", match.minute, odd,
            )
            copy["confidence"] = conf
            copy["value_edge"] = round(conf - (100 / odd), 1)
            copy["goal_step"] = 1 if float(copy["line"]) == targets[0] else 2
        added.append(copy)
        missing.discard(key)
    if added:
        logger.info("KAMBI_FILLED %s %s — %s: %d target lines", match.event_id, match.home, match.away, len(added))
        recs = list(recs) + added

    # Re-select the best FULL_TIME recommendation across all sources.
    for r in recs:
        r.pop("best_bet", None)
    eligible = [r for r in recs if r.get("scope") == "FULL_TIME" and lc._sane_price(r)]
    if eligible:
        def rank(r):
            edge = float(r.get("value_edge", -999))
            conf = float(r.get("confidence", 0))
            step = int(r.get("goal_step", 9) or 9)
            return edge, conf, -step
        max(eligible, key=rank)["best_bet"] = True
    return recs


def _market(entries, match, pressure):
    recs, market = _orig_market(entries, match, pressure)
    recs = _enrich_kambi(recs, match, pressure)
    best = next((r for r in recs if r.get("best_bet") and r.get("scope") == "FULL_TIME" and lc._sane_price(r)), None)
    if best:
        odd = float(best["odd"])
        market = {
            "available": True,
            "scope": "FULL_TIME",
            "line": best["line"],
            "odd": odd,
            "bookmakers": best.get("bookmakers", 1),
            "source": best.get("source", ""),
            "goal_step": best.get("goal_step"),
            "market_probability": round(100 / odd, 1),
        }
    return recs, market


def _evaluate(match, stats, pressure, goals, market):
    qualifies, route, master, scores, hazards, market = _orig_evaluate(match, stats, pressure, goals, market)
    fc = _math_forecast(match)
    if fc:
        p15 = float((fc.get("overs") or {}).get("1.5", 0) or 0)
        p25 = float((fc.get("overs") or {}).get("2.5", 0) or 0)
        bonus = 0.0
        if p15 >= 80:
            bonus += 4.0
        elif p15 >= 72:
            bonus += 2.0
        elif p15 < 58:
            bonus -= 2.0
        if p25 >= 62:
            bonus += 1.0
        elif p25 < 40:
            bonus -= 1.0
        fade = 1.0 if match.minute <= 30 else 0.7 if match.minute <= 60 else 0.4
        bonus = max(-4.0, min(5.0, bonus * fade))
        scores["PREMATCH_MATH"] = max(0.0, min(100.0, 50.0 + bonus * 10.0))
        master = max(0.0, min(100.0, master + bonus))
    # IMPORTANT: `qualifies` remains the original LIVE decision. Math never creates a signal.
    return qualifies, route, master, scores, hazards, market


def _format_strategy_signal(match, pressure, stats, recs, goals, reason, route, master, hazards, market):
    text = _orig_format(match, pressure, stats, recs, goals, reason, route, master, hazards, market)
    fc = _math_forecast(match)
    if not fc:
        return text
    overs = fc.get("overs") or {}
    math_line = (
        "🧮 Прематч-математика: "
        f"xG {float(fc.get('xg_total', 0)):.2f} · "
        f"ТБ1.5 {float(overs.get('1.5', 0)):.0f}% · "
        f"ТБ2.5 {float(overs.get('2.5', 0)):.0f}% · "
        f"ОЗ {float(fc.get('btts', 0)):.0f}%"
    )
    marker = "\n🧠 Рейтинг сигнала:"
    if marker in text:
        return text.replace(marker, f"\n{math_line}{marker}")
    return text + "\n" + math_line


lc._market = _market
lc._evaluate = _evaluate
lc._format_strategy_signal = _format_strategy_signal
