"""Run the existing unified bot with full master-feed LIVE discovery."""
from __future__ import annotations

import asyncio
import unified_bot
from feed_live_discovery import discover_live_matches

# Replace only discovery. All pressure/statistics/Telegram logic remains unchanged.
unified_bot.discover_live_matches = discover_live_matches

if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
