"""Bridge collector JSON snapshots into persistent GOOL Market Server SQLite.

Runs independently from the collector so BEST BET/PROGRUZ always have the last
complete snapshot even while a new all-live scan is in progress.
"""
from __future__ import annotations
import json,logging,os,time
from pathlib import Path
import market_store
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
LOG=logging.getLogger("market_store_bridge")
STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"))
POLL=max(2.0,float(os.getenv("GOOL_MARKET_STORE_POLL","5")))

def _snapshot():
 try:d=json.loads(STATE.read_text(encoding="utf-8"))
 except Exception:return None,[]
 if not isinstance(d,dict):return None,[]
 rows=((d.get("lsapp") or {}).get("records") if isinstance(d.get("lsapp"),dict) else None)
 if not isinstance(rows,list):rows=d.get("records") if isinstance(d.get("records"),list) else []
 return d.get("ts"),rows

def main():
 LOG.info("GOOL MARKET STORE bridge state=%s db=%s",STATE,market_store.DB)
 last=None
 while True:
  ts,rows=_snapshot()
  token=(str(ts),len(rows))
  if rows and token!=last:
   n=market_store.ingest(rows,"flashscore_lsapp")
   if n:
    last=token;LOG.info("MARKET_STORE_COMMIT records=%d health=%s",n,market_store.health())
  time.sleep(POLL)
if __name__=="__main__":main()
