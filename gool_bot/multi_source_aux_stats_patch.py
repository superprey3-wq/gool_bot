"""Apply shared multi-source LIVE statistics to auxiliary strategies.

The auxiliary runtime calls fetch_stats(event_id) followed immediately by
parse_stats(body). We keep the current event in thread-local state and enrich the
parsed Flashscore stats with FotMob/GOAL/365 fallbacks before the strategy sees
or renders them.
"""
from __future__ import annotations

import logging
import threading

import multi_engine_runtime as mer
import multi_source_live_stats as ms

logger = logging.getLogger("multi_source_aux_stats")
_tls = threading.local()
_live_by = {}

_orig_fetch = mer.fetch_stats
_orig_parse = mer.parse_stats
_orig_scan = mer.scan_engines


def _fetch_stats(event_id):
    _tls.event_id = str(event_id or "")
    return _orig_fetch(event_id)


def _parse_stats(body):
    stats = _orig_parse(body)
    eid = str(getattr(_tls, "event_id", "") or "")
    match = _live_by.get(eid)
    if match is None:
        return stats
    try:
        enriched, provenance, _ = ms.enrich(stats, match=match)
        recovered = [k for k, src in provenance.items() if src != "Flashscore"]
        if recovered:
            logger.info("AUX_STATS_RECOVERED event=%s fields=%s sources=%s", eid, recovered, {k: provenance[k] for k in recovered})
        return enriched
    except Exception as exc:
        logger.warning("AUX_STATS_FALLBACK_FAILED event=%s: %s", eid, exc)
        return stats


def _scan_engines(live):
    global _live_by
    _live_by = {str(getattr(m, "event_id", "")): m for m in (live or [])}
    try:
        return _orig_scan(live)
    finally:
        _live_by = {}
        _tls.event_id = ""


mer.fetch_stats = _fetch_stats
mer.parse_stats = _parse_stats
mer.scan_engines = _scan_engines
logger.info("Auxiliary multi-source stats active | field fallback Flashscore -> FotMob/GOAL/365")
