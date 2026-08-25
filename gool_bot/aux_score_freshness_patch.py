"""Synchronize auxiliary ENTRY score with a fresh Flashscore summary.

Stats/timeline are fetched live by the auxiliary engine, while the Match object
comes from the broader discovery cycle and can lag by a goal. Before a signal is
recorded/rendered, refresh only the score from the match summary so an already
scored goal can never become a false post-entry confirmation.
"""
from __future__ import annotations

import logging

import multi_engine_runtime as mer
from daily_report import _score_from_summary

logger = logging.getLogger("aux_score_freshness")

_orig_record = mer._record


def _freshen_score(match):
    eid = str(getattr(match, "event_id", "") or "")
    if not eid:
        return match
    try:
        body = mer.fetch_summary(eid)
        if not body:
            return match
        fh, fa, _hh, _ha = _score_from_summary(body)
        fresh = (int(fh), int(fa))
        old = (int(getattr(match, "home_score", 0) or 0), int(getattr(match, "away_score", 0) or 0))
        # Summary score is monotonic. Never downgrade a fresher discovery score
        # because of a temporarily incomplete summary response.
        if sum(fresh) > sum(old) or (sum(fresh) == sum(old) and fresh != old and sum(fresh) > 0):
            match.home_score, match.away_score = fresh
            logger.warning("AUX_ENTRY_SCORE_SYNC %s %s:%s -> %s:%s minute=%s", eid, old[0], old[1], fresh[0], fresh[1], getattr(match, "minute", 0))
        return match
    except Exception as exc:
        logger.warning("AUX_ENTRY_SCORE_SYNC_FAILED %s: %s", eid, exc)
        return match


def _record(match, engine, score, d, market):
    _freshen_score(match)
    return _orig_record(match, engine, score, d, market)


mer._record = _record
logger.info("Auxiliary ENTRY score freshness active | fresh summary before journal/card")
