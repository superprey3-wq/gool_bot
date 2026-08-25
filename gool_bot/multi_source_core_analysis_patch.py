"""Recover missing CORE LIVE stats before cheap-prefilter and MASTER scoring."""
from __future__ import annotations

import logging

import fast_core_runtime as fcr
import multi_source_live_stats as ms

logger = logging.getLogger("multi_source_core_analysis")
_orig_fetch_one = fcr._fetch_one


def _total(stats, key):
    try:
        a, b = (stats or {}).get(key, (0, 0))
        return float(a or 0) + float(b or 0)
    except Exception:
        return 0.0


def _needs_fallback(stats, match):
    minute = int(getattr(match, "minute", 0) or 0)
    # Missing shots/SOT is always suspicious after the opening phase. Missing xG
    # alone is common in some competitions, so do not spend extra requests for it
    # unless another important field is also absent.
    missing = {
        "shots": _total(stats, "shots") <= 0,
        "sot": _total(stats, "shots_on_target") <= 0,
        "xg": _total(stats, "xg") <= 0,
        "box": _total(stats, "shots_inside_box") <= 0 and _total(stats, "touches_box") <= 0,
    }
    if minute >= 15 and (missing["shots"] or missing["sot"]):
        return True
    return sum(bool(v) for v in missing.values()) >= 3


def _fetch_one(match):
    m, stats = _orig_fetch_one(match)
    if not _needs_fallback(stats, m):
        return m, stats
    try:
        enriched, provenance, _ = ms.enrich(stats, match=m)
        recovered = [k for k, src in provenance.items() if src != "Flashscore"]
        if recovered:
            logger.info("CORE_STATS_RECOVERED event=%s fields=%s sources=%s", getattr(m, "event_id", ""), recovered, {k: provenance[k] for k in recovered})
        return m, enriched
    except Exception as exc:
        logger.warning("CORE_STATS_FALLBACK_FAILED event=%s: %s", getattr(m, "event_id", ""), exc)
        return m, stats


fcr._fetch_one = _fetch_one
logger.info("CORE multi-source analysis active | missing LIVE stats recovered before prefilter")
