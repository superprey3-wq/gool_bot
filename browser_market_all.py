"""Run the v6 Flashscore/LSApp collector across the full LIVE pool.

The base collector keeps conservative caps for small hosts. MonkeyBytes is the
market node, so here we deliberately widen those runtime caps without forking
collector logic: every Flashscore LIVE event returned by the feed is eligible
for an LSApp odds request each cycle.
"""
from __future__ import annotations
import os

# Import the production collector, then widen only runtime limits.
import browser_market_node as node

node.MAX_EVENTS = max(120, int(os.getenv("GOOL_MARKET_ALL_MAX_EVENTS", "250")))
node.MAX_ODDS_EVENTS = node.MAX_EVENTS
node.MAX_RECORDS = max(12000, int(os.getenv("GOOL_MARKET_ALL_MAX_RECORDS", "30000")))
node.MAX_RECORDS_PER_EVENT = max(120, int(os.getenv("GOOL_MARKET_ALL_PER_EVENT", "300")))

if __name__ == "__main__":
    node.LOG.info(
        "GOOL_MARKET_ALL enabled max_events=%d odds_events=%d max_records=%d",
        node.MAX_EVENTS, node.MAX_ODDS_EVENTS, node.MAX_RECORDS,
    )
    node.main()
