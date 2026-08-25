"""Use the shared field-by-field LIVE stats resolver for CORE cards."""
from __future__ import annotations

import copy
import logging

import live_card_quality_patch as lq
import multi_source_live_stats as ms

logger = logging.getLogger("multi_source_core_stats")
_orig_enrich = lq._enrich_pressure


def _providers_from_context(ctx):
    ext = (ctx or {}).get("external_validation") or {}
    return {
        "goal_api": ext.get("goal_api") or {},
        "fotmob": ext.get("fotmob_deep") or ext.get("fotmob") or {},
        "scores365": ext.get("scores365_deep") or ext.get("scores365") or {},
    }


def _enrich_pressure(pressure):
    # Keep existing fail-safe behavior, then extend it with every supported field.
    p = _orig_enrich(pressure)
    stats = dict(getattr(p, "stats", None) or getattr(p, "raw_stats", None) or {})
    ctx = getattr(p, "analysis_context", None) or {}
    try:
        enriched, provenance, _ = ms.enrich(stats, providers=_providers_from_context(ctx))
        p = copy.copy(p)
        p.stats = enriched
        if hasattr(p, "raw_stats"):
            p.raw_stats = enriched
        recovered = [k for k, src in provenance.items() if src != "Flashscore"]
        if recovered:
            logger.info("CORE_CARD_STATS_RECOVERED fields=%s sources=%s", recovered, {k: provenance[k] for k in recovered})
        return p
    except Exception as exc:
        logger.warning("CORE_CARD_MULTI_SOURCE_FAILED: %s", exc)
        return p


# live_card_quality_patch render/reason functions resolve this global at call time.
lq._enrich_pressure = _enrich_pressure
logger.info("CORE multi-source stats active | missing card fields resolved provider-by-provider")
