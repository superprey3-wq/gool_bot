"""Run unified bot with full master-feed discovery and verified LIVE-only odds."""
from __future__ import annotations

import asyncio
import unified_bot
from feed_live_discovery import discover_live_matches as discover_all_live_matches
from live_odds import fetch_live_odds


async def discover_live_matches():
    """Keep tracked matches to FT, but never start monitoring a new match after 85'."""
    matches = await discover_all_live_matches()
    state = unified_bot._load_sent()
    result = []
    for match in matches:
        tracked = f"TRACK:{match.event_id}" in state
        if match.minute <= 85 or tracked:
            result.append(match)
    return result


# Replace only data sources/policy. Pressure, stats, Telegram and tracking logic stay intact.
unified_bot.discover_live_matches = discover_live_matches
unified_bot._fetch_event_odds = fetch_live_odds

if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
