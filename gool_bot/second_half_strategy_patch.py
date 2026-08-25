"""Make SECOND_HALF_OVER15 reachable without weakening match-level safeguards.

Primary decision remains at half-time. If the runner misses the exact HT status,
a stricter recovery decision is allowed at 46-55'. The later 51-55' window is
more selective because the cumulative snapshot already includes opening 2H play.
All entries still pass the shared max-2 / one-open / cooldown / <=75' gate.
"""
from __future__ import annotations

import logging
import re

import league_signal_gate
import multi_engine_runtime as mer
import multi_source_live_stats as ms
from goal_timing import context as timing_context
from live_engine import fetch_stats as raw_fetch_stats, parse_stats as raw_parse_stats
from multi_engine import SECOND_HALF_OVER15, EngineDecision
from risk_controller import can_open
from signal_journal import all_signals

logger = logging.getLogger("second_half_strategy")


def _total(stats, key):
    try:
        a, b = stats.get(key, (0, 0))
        return float(a or 0) + float(b or 0)
    except Exception:
        return 0.0


def _second_half_decision(stats, timing_bonus=0):
    xg = _total(stats, "xg")
    xgot = _total(stats, "xgot")
    shots = _total(stats, "shots")
    sot = _total(stats, "shots_on_target")
    big = _total(stats, "big_chances")
    inside = _total(stats, "shots_inside_box")
    touches = _total(stats, "touches_box")
    corners = _total(stats, "corners")

    raw = xg*20 + xgot*14 + shots*1.35 + sot*4.5 + big*8 + inside*1.2 + touches*.28 + corners*.8
    score = round(max(0.0, min(100.0, raw + float(timing_bonus or 0))), 1)

    checks = [
        (xg >= .85, "xG"),
        (xgot >= .55, "xGoT"),
        (shots >= 9, "shots"),
        (sot >= 3, "SOT"),
        (big >= 1, "big"),
        (inside >= 5, "inside"),
        (touches >= 14, "box_touches"),
        (corners >= 3, "corners"),
    ]
    passed = [name for ok, name in checks if ok]
    eligible = score >= 70 and len(passed) >= 4
    reason = (
        f"1H evidence={len(passed)}/4 [{','.join(passed)}]; "
        f"xG={xg:.2f}; xGoT={xgot:.2f}; shots={shots:.0f}; SOT={sot:.0f}; "
        f"score={score:.1f}; timing={float(timing_bonus or 0):+.1f}"
    )
    logger.info("SECOND_HALF_EVAL eligible=%s %s", eligible, reason)
    return EngineDecision(SECOND_HALF_OVER15, eligible, score, reason)


# The normal HT path in multi_engine_runtime resolves this global at call time.
mer.second_half_over15 = _second_half_decision

_orig_scan = mer.scan_engines


def _has_engine_entry(rows, event_id):
    return any(
        str(r.get("event_id") or "") == str(event_id)
        and str(r.get("engine") or "") == SECOND_HALF_OVER15
        for r in rows
    )


def _recovery_stats(match):
    try:
        body = raw_fetch_stats(match.event_id)
        base = raw_parse_stats(body) if body else {}
        enriched, provenance, _ = ms.enrich(base, match=match)
        return enriched, provenance
    except Exception as exc:
        logger.info("SECOND_HALF_RECOVERY_STATS_FAIL %s: %s", getattr(match, "event_id", ""), exc)
        return {}, {}


def _recovery_thresholds(minute):
    """Later entries need materially stronger evidence than 46-50'."""
    minute = int(minute or 0)
    if minute <= 50:
        return 78.0, 5
    return 82.0, 6


def _scan_recovery(live):
    rows = all_signals()
    seen = eligible = sent = league_reject = cadence_reject = 0
    for m in live or []:
        minute = int(getattr(m, "minute", 0) or 0)
        if bool(getattr(m, "is_halftime", False)) or not (46 <= minute <= 55):
            continue
        if _has_engine_entry(rows, m.event_id):
            continue
        seen += 1
        ok, _profile, why = league_signal_gate.allow(m, SECOND_HALF_OVER15)
        if not ok:
            league_reject += 1
            logger.info("SECOND_HALF_RECOVERY_LEAGUE_REJECT %s %d' %s", m.event_id, minute, why)
            continue
        stats, provenance = _recovery_stats(m)
        if not stats:
            logger.info("SECOND_HALF_RECOVERY_NO_STATS %s %d'", m.event_id, minute)
            continue
        timing = timing_context(m, SECOND_HALF_OVER15)
        dec = _second_half_decision(stats, timing.get("bonus", 0))
        match_evidence = re.search(r"evidence=(\d+)/4", dec.reason)
        evidence = int(match_evidence.group(1)) if match_evidence else 0
        min_score, min_evidence = _recovery_thresholds(minute)
        if not dec.eligible or dec.score < min_score or evidence < min_evidence:
            logger.info(
                "SECOND_HALF_RECOVERY_REJECT %s %d' score=%.1f/%.1f evidence=%d/%d",
                m.event_id, minute, dec.score, min_score, evidence, min_evidence,
            )
            continue
        eligible += 1
        allowed, why = can_open(rows, m.event_id, current_minute=minute)
        if not allowed:
            cadence_reject += 1
            logger.info("SECOND_HALF_RECOVERY_CADENCE_REJECT %s %d' %s", m.event_id, minute, why)
            continue
        d = mer.snapshot(stats)
        d["_timing"] = timing
        d["_decision_reason"] = dec.reason + f"; recovery=46-55; gate={min_score:.0f}/{min_evidence}"
        d["_metric_sources"] = dict(provenance or {})
        market = mer._ht_market(m)
        odd = float(market.get("odd", 0) or 0) if market else None
        if market:
            d["_market"] = {
                "line": market.get("line"), "odd": market.get("odd"),
                "market_status": market.get("market_status"),
                "source_count": market.get("source_count"),
                "source_prices": market.get("source_prices") or [],
            }
        else:
            d["_market"] = {"line": None, "odd": None, "market_status": "NO_PRICE", "source_count": 0, "source_prices": []}
        if mer._record(m, SECOND_HALF_OVER15, dec.score, d, market):
            rows = all_signals()
            if mer._send_all(m, SECOND_HALF_OVER15, dec.score, d, odd):
                sent += 1
    logger.info(
        "SECOND_HALF_RECOVERY_DIAG seen=%d eligible=%d sent=%d league_reject=%d cadence_reject=%d window=46-55",
        seen, eligible, sent, league_reject, cadence_reject,
    )


def scan_engines(live):
    result = _orig_scan(live)
    try:
        _scan_recovery(live)
    except Exception:
        logger.exception("SECOND_HALF_RECOVERY_FAILED")
    return result


mer.scan_engines = scan_engines
logger.info("Second-half strategy patch active | HT primary + 46-55 recovery | 51-55 stricter | diagnostic reasons enabled")
