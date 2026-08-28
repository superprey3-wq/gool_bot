"""Run the validated Flashscore/LSApp collector in the proven lightweight mode.

Do not put SQLite or a full-pool crawl in the critical path. The collector writes
its normal JSON state/history exactly as the old working PROGRUZ pipeline did.
Persistence/extra sources are consumers of that state and may fail independently.
"""
from __future__ import annotations
import os
import browser_market_node as node

# Keep the validated collector's bounded live scan. Environment variables allow
# gradual increases later, but defaults deliberately match the stable v6 design.
node.MAX_EVENTS=max(20,min(100,int(os.getenv("GOOL_MARKET_MAX_EVENTS","60"))))
node.MAX_ODDS_EVENTS=max(4,min(24,int(os.getenv("GOOL_MARKET_ODDS_EVENTS","12"))))
node.MAX_RECORDS=max(300,min(3000,int(os.getenv("GOOL_MARKET_MAX_RECORDS","1800"))))
node.MAX_RECORDS_PER_EVENT=max(80,min(500,int(os.getenv("GOOL_MARKET_PER_EVENT","260"))))

if __name__=="__main__":
 node.LOG.info("GOOL_MARKET_LIVE restored stable mode events=%d odds_events=%d records=%d",node.MAX_EVENTS,node.MAX_ODDS_EVENTS,node.MAX_RECORDS)
 node.main()
