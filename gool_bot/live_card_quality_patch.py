"""Make GOOL entry cards resilient and honest about LIVE data quality.

- A failed pre-send live refresh must never discard an already-qualified signal.
- Card metrics may be enriched from GOAL API/FotMob/365Scores when the primary
  Flashscore pressure object has missing zero-valued fields.
- External sources count as analytical sources only when they actually returned
  useful football data, not merely when team matching succeeded.
"""
from __future__ import annotations

import copy
import logging
from statistics import median

import signal_card as sc
import telegram_image_signal_patch as tip

logger = logging.getLogger("live_card_quality")


# 1) Never lose an ENTRY card only because the last-second refresh timed out.
_original_sync_entry_match = tip._sync_entry_match


def _sync_entry_match_failopen(match):
    fresh = _original_sync_entry_match(match)
    if fresh is not None:
        return fresh
    logger.warning(
        "ENTRY_CARD_REFRESH_FAILED %s; rendering from qualified signal snapshot",
        getattr(match, "event_id", ""),
    )
    return copy.copy(match)


tip._sync_entry_match = _sync_entry_match_failopen


def _ext(ctx):
    return (ctx or {}).get("external_validation") or {}


def _fot_features(ext):
    deep = ext.get("fotmob_deep") or {}
    base = ext.get("fotmob") or {}
    return (deep.get("features") or base.get("features") or {}) if isinstance(deep, dict) and isinstance(base, dict) else {}


def _s365_features(ext):
    deep = ext.get("scores365_deep") or {}
    base = ext.get("scores365") or {}
    # 365 deep features are already flat; candidate features are flat too.
    row = deep if isinstance(deep, dict) and deep else base
    return row if isinstance(row, dict) else {}


def _useful_goal(ext):
    row = ext.get("goal_api") or {}
    stats = row.get("stats") or {} if isinstance(row, dict) else {}
    return bool(row.get("matched") and isinstance(stats, dict) and stats)


def _useful_fot(ext):
    row = ext.get("fotmob_deep") or ext.get("fotmob") or {}
    f = _fot_features(ext)
    return bool(
        isinstance(row, dict)
        and row.get("matched")
        and (
            int(f.get("shotmap_n") or 0) > 0
            or f.get("shot_xg_total") is not None
            or f.get("shot_xgot_total") is not None
            or f.get("xg_node") is not None
            or f.get("big_chances_node") is not None
            or f.get("touches_box_node") is not None
        )
    )


def _useful_365(ext):
    row = ext.get("scores365_deep") or ext.get("scores365") or {}
    f = _s365_features(ext)
    return bool(
        isinstance(row, dict)
        and row.get("matched")
        and (
            int(f.get("shots") or 0) > 0
            or f.get("shot_xg_total") is not None
            or f.get("shot_xgot_total") is not None
            or bool(f.get("has_stats"))
            or bool(f.get("has_shotmap"))
        )
    )


def _source_summary(ctx):
    ext = _ext(ctx)
    names = ["Flashscore"]
    if _useful_goal(ext):
        names.append("GOAL API")
    if _useful_fot(ext):
        names.append("FotMob")
    if _useful_365(ext):
        names.append("365Scores")
    if (ctx or {}).get("history"):
        names.append("Form/H2H")
    return names


sc._source_summary = _source_summary


def _pair_total(stats, key):
    try:
        a, b = stats.get(key, (0, 0))
        return float(a or 0) + float(b or 0)
    except Exception:
        return 0.0


def _positive_median(values):
    vals = []
    for value in values:
        try:
            if value is not None and float(value) >= 0:
                vals.append(float(value))
        except Exception:
            pass
    return median(vals) if vals else None


def _enrich_pressure(pressure):
    p = copy.copy(pressure)
    stats = dict(getattr(pressure, "stats", None) or getattr(pressure, "raw_stats", None) or {})
    ctx = getattr(pressure, "analysis_context", None) or {}
    ext = _ext(ctx)
    fot = _fot_features(ext)
    sx = _s365_features(ext)

    # xG/xGoT: use cross-source median only when the primary card field is missing.
    if _pair_total(stats, "xg") <= 0:
        xg = _positive_median([fot.get("shot_xg_total"), sx.get("shot_xg_total")])
        if xg is not None and xg > 0:
            stats["xg"] = (round(xg, 3), 0.0)
    if _pair_total(stats, "xgot") <= 0:
        xgot = _positive_median([fot.get("shot_xgot_total"), sx.get("shot_xgot_total")])
        if xgot is not None and xgot > 0:
            stats["xgot"] = (round(xgot, 3), 0.0)

    # Total shots: do not add providers together; use the strongest observed count.
    if _pair_total(stats, "shots") <= 0:
        candidates = []
        for value in (fot.get("shotmap_n"), sx.get("shots")):
            try:
                if int(value or 0) > 0:
                    candidates.append(int(value))
            except Exception:
                pass
        if candidates:
            stats["shots"] = (max(candidates), 0)

    # Shots on target from GOAL API if Flashscore's detailed stats are absent.
    if _pair_total(stats, "shots_on_target") <= 0:
        goal = ext.get("goal_api") or {}
        gs = goal.get("stats") or {} if isinstance(goal, dict) else {}
        sot = gs.get("on target") or gs.get("shots on goal") or gs.get("shots on target")
        try:
            if sot and sum(float(x or 0) for x in sot) > 0:
                stats["shots_on_target"] = tuple(float(x or 0) for x in sot[:2])
        except Exception:
            pass

    p.stats = stats
    if hasattr(p, "raw_stats"):
        p.raw_stats = stats
    return p


_original_reason = sc._reason


def _reason_quality(pressure, recs, probs):
    p = _enrich_pressure(pressure)
    stats = getattr(p, "stats", None) or {}
    observed = _pair_total(stats, "shots") + _pair_total(stats, "shots_on_target")
    observed += _pair_total(stats, "xg") + _pair_total(stats, "xgot")
    reasons = _original_reason(p, recs, probs)
    if observed <= 0:
        # Do not claim stable LIVE pressure when no provider supplied live event stats.
        reasons = [r for r in reasons if "LIVE-давление" not in r and "Темп подтверждён" not in r and not r.startswith("xG ")]
        reasons.insert(0, "LIVE DATA LIMITED: подробные удары/xG от источников сейчас недоступны; сигнал опирается на доступные игровые и контекстные блоки.")
    elif _pair_total(getattr(pressure, "stats", None) or {}, "shots") <= 0:
        reasons.insert(0, "LIVE-метрики восстановлены по независимым FotMob/365Scores/GOAL данным, потому что основной detailed feed был неполным.")
    return reasons[:5]


sc._reason = _reason_quality


_original_render = sc.render_signal_card


def _render_signal_card(match, pressure, recs=None, kind="entry", master=None, probabilities=None):
    enriched = _enrich_pressure(pressure) if kind == "entry" else pressure
    return _original_render(match, enriched, recs, kind=kind, master=master, probabilities=probabilities)


# telegram_image_signal_patch imported the renderer by name, so patch both refs.
sc.render_signal_card = _render_signal_card
tip.render_signal_card = _render_signal_card

logger.info("LIVE card quality patch active | entry refresh fail-open | substantive source counting | external stat display fallback")
