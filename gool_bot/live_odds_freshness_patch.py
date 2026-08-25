"""Keep candidate-only fallback LIVE prices close to the signal moment.

Flashscore/LSApp is already fetched directly for every selected candidate. The
fallback Bovada and Kambi adapters historically cached for 25 seconds; reduce
that window so a selected GOOL entry is not confirmed by an old fallback quote.
"""
from __future__ import annotations
import logging
import bovada_live_odds
import kambi_live_odds

logger=logging.getLogger("live_odds_freshness")
MAX_FALLBACK_CACHE_SECONDS=8
bovada_live_odds._CACHE_TTL=MAX_FALLBACK_CACHE_SECONDS
kambi_live_odds._CACHE_SECONDS=MAX_FALLBACK_CACHE_SECONDS
logger.info("LIVE odds freshness enabled: LSApp direct; Bovada/Kambi cache <= %ss",MAX_FALLBACK_CACHE_SECONDS)
