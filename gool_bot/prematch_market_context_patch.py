"""Attach GOOL 2.0 PREMATCH market history to LIVE evaluation.

Observation-only bridge. It exposes the exact event_id-linked prematch dossier to
LIVE without changing qualification, score, or signal thresholds. Future model
versions can learn which market movements are genuinely predictive before those
features are allowed to affect decisions.
"""
from __future__ import annotations

import logging
from typing import Any

import live_candidate_patch as lc
from prematch_market_service import get_prematch_context

logger = logging.getLogger("prematch_market_context")
_orig = lc._evaluate


def _move_summary(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    summary = snapshot.get("market_summary") or {}
    rows = summary.get("largest_moves") or []
    out = []
    for row in rows[:12]:
        if not isinstance(row, dict):
            continue
        mv = row.get("movement") or {}
        out.append({
            "market": row.get("market"),
            "scope": row.get("scope"),
            "selection": row.get("selection"),
            "participant_id": row.get("participant_id"),
            "line": row.get("line"),
            "bookmaker_id": row.get("bookmaker_id"),
            "opening": mv.get("opening", row.get("opening")),
            "current": mv.get("current", row.get("current")),
            "move_pp": mv.get("move_pp"),
        })
    return out


def _compact(ctx: dict[str, Any]) -> dict[str, Any]:
    first = ctx.get("first_snapshot") or {}
    final = ctx.get("final_prematch") or ctx.get("latest_snapshot") or {}
    return {
        "available": True,
        "kickoff_ts": ctx.get("kickoff_ts"),
        "tracking_state": ctx.get("tracking_state"),
        "snapshots_count": int(ctx.get("snapshots_count", 0) or 0),
        "first_market_ts": first.get("captured_ts"),
        "final_market_ts": final.get("captured_ts"),
        "market_types": ((final.get("market_summary") or {}).get("market_types") or []),
        "scopes": ((final.get("market_summary") or {}).get("scopes") or []),
        "bookmakers": ((final.get("market_summary") or {}).get("bookmakers") or []),
        "largest_moves": _move_summary(final),
    }


def _evaluate(m, s, p, goals, market):
    result = _orig(m, s, p, goals, market)
    qualifies, route, master, scores, hz, market = result
    try:
        ctx = get_prematch_context(str(getattr(m, "event_id", "") or ""))
        if ctx:
            compact = _compact(ctx)
            market["prematch_market_context"] = compact
            setattr(m, "prematch_market_context", compact)
            # Neutral diagnostic score only. This feature cannot affect qualification.
            scores["PREMATCH_MARKET_OBSERVED"] = 50.0
            logger.info(
                "PREMATCH_TO_LIVE %s snapshots=%d moves=%d markets=%d",
                getattr(m, "event_id", "?"),
                compact["snapshots_count"],
                len(compact["largest_moves"]),
                len(compact["market_types"]),
            )
        else:
            market["prematch_market_context"] = {"available": False}
    except Exception as exc:
        logger.info("PREMATCH_TO_LIVE_FAILED %s %s", getattr(m, "event_id", "?"), exc)
    return qualifies, route, master, scores, hz, market


lc._evaluate = _evaluate
logger.info("PREMATCH->LIVE bridge active in observation-only mode")
