"""Run Flashscore/LSApp collector across full LIVE pool with persistent snapshots."""
from __future__ import annotations
import json,os
import browser_market_node as node
import market_store

node.MAX_EVENTS=max(120,int(os.getenv("GOOL_MARKET_ALL_MAX_EVENTS","250")))
node.MAX_ODDS_EVENTS=node.MAX_EVENTS
node.MAX_RECORDS=max(12000,int(os.getenv("GOOL_MARKET_ALL_MAX_RECORDS","30000")))
node.MAX_RECORDS_PER_EVENT=max(120,int(os.getenv("GOOL_MARKET_ALL_PER_EVENT","300")))

# Persist only atomically completed state files. BEST BET can keep reading the
# previous good DB snapshot while the next network collection is in progress.
_orig_atomic=node._atomic_json
def _atomic_and_store(path,payload):
 _orig_atomic(path,payload)
 try:
  if str(path)==str(node.STATE_FILE):
   ls=(payload or {}).get("lsapp") or {};rows=ls.get("records") or []
   n=market_store.ingest(rows,"flashscore_lsapp") if rows else 0
   node.LOG.info("MARKET_DB snapshot records=%d health=%s",n,market_store.health())
 except Exception as exc:node.LOG.warning("MARKET_DB ingest failed: %s",exc)
node._atomic_json=_atomic_and_store

if __name__=="__main__":
 node.LOG.info("GOOL_MARKET_ALL enabled max_events=%d odds_events=%d max_records=%d sqlite=on",node.MAX_EVENTS,node.MAX_ODDS_EVENTS,node.MAX_RECORDS)
 node.main()
