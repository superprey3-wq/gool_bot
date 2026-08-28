"""Headless BEST BET worker for the MonkeyBytes market node.

Runs the independent BEST BET analysis on Monkey market-state data and captures
approved bets into a small JSON feed instead of sending Telegram directly. The
primary GOOL server relays the feed with its existing subscribers/token.
"""
from __future__ import annotations
import asyncio,json,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("best_bet_remote_worker")
STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"))
POLL=max(30,int(os.getenv("GOOL_REMOTE_BEST_BET_POLL_SECONDS","60")))

# Keep the same runtime market/data patches as production BEST BET.
import visual_feed_unified_bot
import xg_proxy_patch
import live_only_recommendation_patch
import live_candidate_patch
import candidate_enrichment_patch
import scores365_enrichment_patch
import deep_stats_consensus_patch
import context_adjustment_patch
import period_market_patch
import phase_market_patch
import multi_source_odds_patch
import live_odds_freshness_patch
import btts_period_sources_patch
import team_total_sources_patch
import sportsgameodds_patch
import best_market_selector_patch
import score_sync_patch
import market_math_patch
import gool_xg_consensus
import odds_nonblocking_patch
import best_bet_input_reliability_patch
import best_bet_engine as bbe
import best_bet_consensus_patch
import best_bet_delivery_reliability_patch
# Final input layer: consume Monkey's normalized 1X2/TOTAL/AH/BTTS/DC/DNB state.
import best_bet_market_state_patch

_last_capture=None

def _capture_send(_png,caption):
 global _last_capture
 _last_capture={"caption":caption,"ts":int(time.time())}
 return True

# Do not contact Telegram from MonkeyBytes. Approval is captured locally.
bbe._send=_capture_send

def _write(payload):
 try:
  tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATE)
 except Exception as exc:log.warning("REMOTE_BEST_BET state write failed: %s",exc)

def _latest_best_bet():
 try:
  from signal_journal import all_signals
  rows=[r for r in all_signals() if r.get('kind')=='best_bet']
  if not rows:return None
  return max(rows,key=lambda r:int(r.get('created_ts',0) or r.get('last_seen_ts',0) or 0))
 except Exception:return None

async def cycle():
 global _last_capture
 _last_capture=None
 live=await visual_feed_unified_bot.unified_bot.discover_live_matches()
 score_sync_patch.reuse_once(live)
 sent=await asyncio.to_thread(bbe.scan,live)
 row=_latest_best_bet()
 payload={"ts":int(time.time()),"live":len(live),"sent":int(sent),"signal":row if sent and row else None,"capture":_last_capture}
 _write(payload)
 log.info("REMOTE_BEST_BET_SCAN live=%d sent=%d signal=%s",len(live),sent,(row or {}).get('primary'))

async def main():
 log.info("GOOL REMOTE BEST BET worker online poll=%ss state=%s",POLL,STATE)
 while True:
  started=time.monotonic()
  try:await cycle()
  except Exception:log.exception("REMOTE BEST BET cycle failed; continuing")
  await asyncio.sleep(max(2.0,POLL-(time.monotonic()-started)))

if __name__=='__main__':asyncio.run(main())
