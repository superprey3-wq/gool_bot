"""24/7 GOOL LIVE production runner."""
from __future__ import annotations
import asyncio,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD","75");os.environ.setdefault("LIVE_COOLDOWN_MINUTES","12")
LIVE_INTERVAL_SECONDS=max(30,int(os.getenv("LIVE_INTERVAL_SECONDS","60")))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");logger=logging.getLogger("gool_live_24x7")
import visual_feed_unified_bot
import xg_proxy_patch
import live_only_recommendation_patch
import live_candidate_patch
import candidate_enrichment_patch
import scores365_enrichment_patch
import deep_stats_consensus_patch
import context_adjustment_patch
import core_warmup_patch
import halftime_hazard_patch
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
import telegram_signal_filter_patch
import telegram_image_signal_patch
import analytics_card_fallback_patch
import entry_sync_failopen_patch
import live_quant_guard_patch
import robust_goal_cooldown_patch
import fast_core_runtime
import signal_journal_runtime_patch
import core_goal_signal_patch
import goal_reset_patch
import core_primary_reconcile
import clv_tracker
import live_status_heartbeat
import fast_goal_watch
import multi_engine_runtime
import live_button_patch
import live_button_emergency_patch
from league_signal_gate import filter_for_multi_engine
from telegram_subscribers import polling_loop
import production_logging
async def run_live():
 try:
  started=time.monotonic();live=await visual_feed_unified_bot.unified_bot.discover_live_matches();discovery=time.monotonic()-started
  score_sync_patch.reuse_once(live)
  await visual_feed_unified_bot.unified_bot.scan_live_once()
  engine_live=await asyncio.to_thread(filter_for_multi_engine,live)
  await asyncio.to_thread(multi_engine_runtime.scan_engines,engine_live)
  await asyncio.to_thread(core_primary_reconcile.reconcile,live)
  await asyncio.to_thread(clv_tracker.sample,live)
  logger.info("GOOL_CYCLE_DONE live=%d aux=%d discovery=%.1fs total=%.1fs",len(live),len(engine_live),discovery,time.monotonic()-started)
 except Exception:logger.exception("LIVE scan failed; runner will continue")
async def status_loop():
 while True:
  await asyncio.sleep(live_status_heartbeat.STATUS_INTERVAL_SECONDS)
  try:await asyncio.to_thread(live_status_heartbeat.send_heartbeat)
  except Exception:logger.exception("LIVE heartbeat failed; runner will continue")
async def main():
 poller=asyncio.create_task(polling_loop(),name="telegram-command-poller");heartbeat=asyncio.create_task(status_loop(),name="live-status-heartbeat");goal_watch=asyncio.create_task(fast_goal_watch.loop(),name="fast-goal-watch")
 logger.info("GOOL LIVE | analytics drive signals: Flashscore + history/H2H + GOAL API + FotMob + 365Scores + xG context | odds optional metadata only")
 try:
  while True:
   started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
 finally:
  poller.cancel();heartbeat.cancel();goal_watch.cancel();await asyncio.gather(poller,heartbeat,goal_watch,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())
