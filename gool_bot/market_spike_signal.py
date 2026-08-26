"""Legacy market spike sender disabled.

All owner-only sharp-market alerts are now handled exclusively by
market_test_signal.py (TOP-5 full-match totals, LIVE / next 2h, one alert per match).
This module remains as a compatibility shim because older runners import it.
"""
from __future__ import annotations

import logging

log = logging.getLogger("market_spike_signal")


def scan_once() -> int:
    """Compatibility no-op: legacy ПРОГРУЗ РЫНКА delivery is permanently disabled."""
    log.debug("MARKET_SPIKE_LEGACY_DISABLED")
    return 0
