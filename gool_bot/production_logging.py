"""Production logging profile for GOOL LIVE."""
from __future__ import annotations
import logging,os
DEBUG=str(os.getenv("GOOL_DEBUG","0")).strip().lower() in {"1","true","yes","on"}
NOISY_LOGGERS=("live_candidate_patch","gool_xg_consensus","telegram_signal_filter_patch","phase_market_patch","period_market_patch","market_math_patch","score_sync_patch","halftime_hazard_patch","unified_bot","live_engine","bovada_live_odds","kambi_live_odds","live_odds","visual_feed_unified_bot","candidate_enrichment","scores365_enrichment")
for name in NOISY_LOGGERS:logging.getLogger(name).setLevel(logging.DEBUG if DEBUG else logging.WARNING)
logging.getLogger("gool_live_24x7").setLevel(logging.DEBUG if DEBUG else logging.INFO)
logging.getLogger("telegram_image_signal_patch").setLevel(logging.DEBUG if DEBUG else logging.INFO)
logging.getLogger("telegram_subscribers").setLevel(logging.DEBUG if DEBUG else logging.WARNING)
if DEBUG:logging.getLogger().setLevel(logging.DEBUG)
