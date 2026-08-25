"""Resolve missing LIVE football statistics across independent providers.

Priority is field-by-field, not provider-by-provider. Flashscore remains primary;
missing fields are filled from FotMob, GOAL API and 365Scores without summing
providers together. Provenance is returned so cards/logs can say where each
metric came from.
"""
from __future__ import annotations

import copy
import logging
from statistics import median

import candidate_enrichment_patch as ce
import scores365_enrichment_patch as s365

logger = logging.getLogger("multi_source_live_stats")


def _pair_total(stats, key):
    try:
        a, b = stats.get(key, (0, 0))
        return float(a or 0) + float(b or 0)
    except Exception:
        return 0.0


def _pair(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return float(value[0] or 0), float(value[1] or 0)
        except Exception:
            return None
    return None


def _scalar(value):
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except Exception:
        return None


def _node_total(value):
    """Best-effort total from FotMob stat nodes, which vary by competition."""
    if value is None:
        return None
    p = _pair(value)
    if p:
        return p[0] + p[1]
    if isinstance(value, dict):
        vals = []
        for k in ("home", "away", "homeValue", "awayValue", "value"):
            v = _scalar(value.get(k))
            if v is not None:
                vals.append(v)
        if vals:
            return sum(vals[:2])
    if isinstance(value, list):
        vals = [_scalar(v) for v in value]
        vals = [v for v in vals if v is not None]
        if vals:
            return sum(vals[:2])
    return _scalar(value)


def _goal_metric(gs, *names):
    for name in names:
        value = gs.get(name)
        p = _pair(value)
        if p and (p[0] > 0 or p[1] > 0):
            return p
    return None


def _positive_median(values):
    vals = []
    for value in values:
        v = _scalar(value)
        if v is not None and v > 0:
            vals.append(v)
    return median(vals) if vals else None


def provider_payload(match):
    """Fetch provider features once for a match. Failures are isolated."""
    try:
        goal = ce._goal_stats(match)
    except Exception as exc:
        logger.debug("GOAL stats fallback failed %s: %s", getattr(match, "event_id", ""), exc)
        goal = {"matched": False}
    try:
        fot = ce._fotmob_features(match)
    except Exception as exc:
        logger.debug("FotMob stats fallback failed %s: %s", getattr(match, "event_id", ""), exc)
        fot = {"matched": False}
    try:
        sx = s365._features(match)
    except Exception as exc:
        logger.debug("365Scores stats fallback failed %s: %s", getattr(match, "event_id", ""), exc)
        sx = {"matched": False}
    return {"goal_api": goal or {}, "fotmob": fot or {}, "scores365": sx or {}}


def enrich(stats, match=None, providers=None):
    """Return (stats, provenance, providers) with only missing fields filled."""
    out = copy.deepcopy(stats or {})
    provenance = {k: "Flashscore" for k in out if not str(k).startswith("_") and _pair_total(out, k) > 0}
    providers = providers or (provider_payload(match) if match is not None else {})

    goal = providers.get("goal_api") or {}
    gs = (goal.get("stats") or {}) if isinstance(goal, dict) else {}
    fot = providers.get("fotmob") or {}
    ff = (fot.get("features") or {}) if isinstance(fot, dict) else {}
    sx = providers.get("scores365") or {}

    # xG/xGoT: consensus if both secondary sources have it; never add providers.
    if _pair_total(out, "xg") <= 0:
        v = _positive_median([ff.get("shot_xg_total"), sx.get("shot_xg_total")])
        if v is not None:
            out["xg"] = (round(v, 3), 0.0)
            provenance["xg"] = "FotMob+365Scores" if ff.get("shot_xg_total") is not None and sx.get("shot_xg_total") is not None else ("FotMob" if ff.get("shot_xg_total") is not None else "365Scores")
    if _pair_total(out, "xgot") <= 0:
        v = _positive_median([ff.get("shot_xgot_total"), sx.get("shot_xgot_total")])
        if v is not None:
            out["xgot"] = (round(v, 3), 0.0)
            provenance["xgot"] = "FotMob+365Scores" if ff.get("shot_xgot_total") is not None and sx.get("shot_xgot_total") is not None else ("FotMob" if ff.get("shot_xgot_total") is not None else "365Scores")

    # Shots: prefer FotMob shotmap, then 365Scores, then GOAL API totals.
    if _pair_total(out, "shots") <= 0:
        fshots = int(ff.get("shotmap_n") or 0)
        sshots = int(sx.get("shots") or 0)
        gshots = _goal_metric(gs, "total shots", "shots", "shots total")
        if fshots > 0:
            out["shots"] = (float(fshots), 0.0); provenance["shots"] = "FotMob"
        elif sshots > 0:
            out["shots"] = (float(sshots), 0.0); provenance["shots"] = "365Scores"
        elif gshots:
            out["shots"] = gshots; provenance["shots"] = "GOAL API"

    # Shots on target: GOAL API is the strongest currently parsed fallback.
    if _pair_total(out, "shots_on_target") <= 0:
        p = _goal_metric(gs, "on target", "shots on goal", "shots on target")
        if p:
            out["shots_on_target"] = p; provenance["shots_on_target"] = "GOAL API"

    # Big chances: FotMob exposes this in many competitions; GOAL may expose it too.
    if _pair_total(out, "big_chances") <= 0:
        fv = _node_total(ff.get("big_chances_node"))
        gp = _goal_metric(gs, "big chances", "big chance")
        if fv is not None and fv > 0:
            out["big_chances"] = (fv, 0.0); provenance["big_chances"] = "FotMob"
        elif gp:
            out["big_chances"] = gp; provenance["big_chances"] = "GOAL API"

    # Box activity. Prefer true shots-inside-box from GOAL; FotMob touches-box is a
    # related but distinct metric, so keep it as touches_box instead of mislabelling.
    if _pair_total(out, "shots_inside_box") <= 0:
        gp = _goal_metric(gs, "shots inside box", "shots inside the box")
        if gp:
            out["shots_inside_box"] = gp; provenance["shots_inside_box"] = "GOAL API"
    if _pair_total(out, "touches_box") <= 0:
        fv = _node_total(ff.get("touches_box_node"))
        gp = _goal_metric(gs, "touches in opposition box", "touches in box")
        if fv is not None and fv > 0:
            out["touches_box"] = (fv, 0.0); provenance["touches_box"] = "FotMob"
        elif gp:
            out["touches_box"] = gp; provenance["touches_box"] = "GOAL API"

    out["_metric_sources"] = provenance
    out["_provider_presence"] = {
        "Flashscore": bool(stats),
        "GOAL API": bool(goal.get("matched") and gs),
        "FotMob": bool(fot.get("matched") and ff),
        "365Scores": bool(sx.get("matched") and (sx.get("shots") or sx.get("shot_xg_total") is not None or sx.get("has_stats"))),
    }
    return out, provenance, providers


def source_label(stats, key):
    return str((stats or {}).get("_metric_sources", {}).get(key) or "")


logger.info("Multi-source LIVE stats resolver active | Flashscore > field fallbacks FotMob/GOAL/365")
