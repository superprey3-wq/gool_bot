"""Keep external confirmation prices close to the signal moment.

Flashscore/LSApp is fetched directly for each selected candidate and is the
source of truth. Kambi/BetRivers is confirmation-only and uses a short cache.
"""
from __future__ import annotations
import logging
import kambi_live_odds

logger=logging.getLogger("live_odds_freshness")
MAX_CONFIRMATION_CACHE_SECONDS=8
kambi_live_odds._CACHE_SECONDS=MAX_CONFIRMATION_CACHE_SECONDS
logger.info("LIVE odds freshness: Flashscore/LSApp direct; Kambi confirmation cache <= %ss",MAX_CONFIRMATION_CACHE_SECONDS)
