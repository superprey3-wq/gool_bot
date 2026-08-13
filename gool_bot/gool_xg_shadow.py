"""Shadow-mode GOOL XG consensus diagnostics.

Runs the experimental XG consensus for every LIVE evaluation but returns the
existing production decision unchanged. No MASTER/grade/Telegram behavior is
modified. This module is intended only for real-match calibration in logs.
"""
from __future__ import annotations

import logging

import live_candidate_patch as lc
import market_math_patch  # noqa: F401 - ensure current production math patch is installed first
import gool_xg_consensus as gx

logger = logging.getLogger("gool_xg_shadow")

# Importing gool_xg_consensus temporarily installs its experimental wrappers.
# For shadow mode, restore the production formatter and wrap the production
# evaluator only to compute diagnostics before returning the untouched result.
_PROD_EVALUATE = gx._orig_evaluate
_PROD_FORMAT = gx._orig_format


def _shadow_evaluate(match, stats, pressure, goals, market):
    result = _PROD_EVALUATE(match, stats, pressure, goals, market)
    qualifies, route, master, scores, hazards, resolved_market = result
    try:
        model = gx._consensus(match, stats, resolved_market)
        c = model.get("components") or {}
        logger.info(
            "GOOL_XG_SHADOW %d' %s — %s | strength=%s market=%s real=%s calc=%s | lambda=%.2f pGoal=%.0f%% agree=%.0f%% sources=%d score=%.0f | PROD master=%.0f route=%s qualifies=%s",
            int(getattr(match, "minute", 0) or 0),
            getattr(match, "home", ""),
            getattr(match, "away", ""),
            c.get("strength"),
            c.get("market"),
            c.get("real"),
            c.get("calc"),
            float(model.get("lambda", 0) or 0),
            float(model.get("goal_probability", 0) or 0),
            float(model.get("agreement", 0) or 0),
            int(model.get("sources", 0) or 0),
            float(model.get("score", 0) or 0),
            float(master or 0),
            route,
            qualifies,
        )
    except Exception as exc:
        logger.info(
            "GOOL_XG_SHADOW_FAILED %s %s — %s: %s",
            getattr(match, "event_id", ""),
            getattr(match, "home", ""),
            getattr(match, "away", ""),
            exc,
        )
    # Critical safety property: return production output byte-for-byte in shape
    # and without editing scores/master/route/qualifies.
    return result


lc._evaluate = _shadow_evaluate
lc._format_strategy_signal = _PROD_FORMAT
logger.info("GOOL XG shadow mode enabled: diagnostics only; production decisions unchanged")
