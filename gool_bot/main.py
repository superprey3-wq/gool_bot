"""24/7 GOOL LIVE production runner."""
from __future__ import annotations
import asyncio,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD","75");os.environ.setdefault("LIVE_COOLDOWN_MINUTES","12")
LIVE_INTERVAL_SECONDS=max(30,int(os.getenv("LIVE_INTERVAL_SECONDS","60")))
BETB2B_INTERVAL_SECONDS=max(45,int(os.getenv("BETB2B_INTERVAL_SECONDS","60")))
MARKET_NODE_PULL_SECONDS=max(10,int(os.getenv("MARKET_NODE_PULL_SECONDS","15")))
MEMORY_DIAG_SECONDS=max(5,int(os.getenv("MEMORY_DIAG_SECONDS","10")))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");logger=logging.getLogger("gool_live_24x7")

def _rss_mb():
 try:
  with open("/proc/self/status","r",encoding="utf-8") as fh:
   for line in fh:
    if line.startswith("VmRSS:"):
     return round(int(line.split()[1])/1024.0,1)
 except Exception:
  pass
 return -1.0

def _mem(stage):
 logger.info("MEM_DIAG stage=%s rss_mb=%.1f",stage,_rss_mb())

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
import betb2b_market_signal
import market_node_bridge
import telegram_image_signal_patch
import analytics_card_fallback_patch
import live_card_quality_patch
import entry_card_delivery_patch
import multi_source_core_stats_patch
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
import confirmation_integrity_patch
import multi_engine_runtime
import betb2b_card_patch
import aux_score_freshness_patch
import multi_source_aux_stats_patch
import second_half_strategy_patch
import card_explainability_patch
import second_half_card_reason_patch
import aux_result_minute_patch
import release_build_patch
from league_signal_gate import filter_for_multi_engine
import telegram_subscribers
import telegram_interactive_live_patch
import market_test_signal
from telegram_subscribers import polling_loop,BUILD_ID
import production_logging
_mem("imports_done")

async def run_live():
 try:
  _mem("cycle_start")
  started=time.monotonic();live=await visual_feed_unified_bot.unified_bot.discover_live_matches();discovery=time.monotonic()-started
  _mem("after_discovery")
  score_sync_patch.reuse_once(live)
  _mem("after_score_sync")
  await visual_feed_unified_bot.unified_bot.scan_live_once()
  _mem("after_scan_live_once")
  engine_live=await asyncio.to_thread(filter_for_multi_engine,live)
  _mem("after_filter_multi_engine")
  await asyncio.to_thread(multi_engine_runtime.scan_engines,engine_live)
  _mem("after_multi_engine")
  await asyncio.to_thread(core_primary_reconcile.reconcile,live)
  _mem("after_reconcile")
  await asyncio.to_thread(clv_tracker.sample,live)
  _mem("after_clv")
  logger.info("GOOL_CYCLE_DONE live=%d aux=%d discovery=%.1fs total=%.1fs",len(live),len(engine_live),discovery,time.monotonic()-started)
 except Exception:logger.exception("LIVE scan failed; runner will continue")
async def status_loop():
 while True:
  await asyncio.sleep(live_status_heartbeat.STATUS_INTERVAL_SECONDS)
  try:await asyncio.to_thread(live_status_heartbeat.send_heartbeat)
  except Exception:logger.exception("LIVE heartbeat failed; runner will continue")
async def betb2b_loop():
 while True:
  try:
   _mem("betb2b_before")
   await asyncio.to_thread(betb2b_market_signal.sample_live)
   _mem("betb2b_after")
  except Exception:logger.exception("BETB2B sample failed; runner will continue")
  await asyncio.sleep(BETB2B_INTERVAL_SECONDS)
async def market_node_loop():
 while True:
  if market_node_bridge.URL:
   try:
    _mem("market_node_before")
    n=await asyncio.to_thread(market_node_bridge.poll_once)
    _mem("market_node_after")
    if n:
     h=market_node_bridge.health();logger.info("PROGRUZ_ONLINE events=%d age=%.1fs",h.get("events",0),max(0.,time.time()-float(h.get("last_ok",time.time()) or time.time())))
   except Exception:logger.exception("Remote market node pull failed; runner will continue")
  await asyncio.sleep(MARKET_NODE_PULL_SECONDS)
async def market_test_loop():
 while True:
  try:
   await asyncio.sleep(3)
   _mem("market_test_before")
   sent=await asyncio.to_thread(market_test_signal.scan_once)
   _mem("market_test_after")
   if sent:logger.info("MARKET_TEST batch_sent=%d",sent)
  except Exception:logger.exception("MARKET TEST scan failed; runner will continue")
  await asyncio.sleep(MARKET_NODE_PULL_SECONDS)
async def memory_watchdog():
 while True:
  await asyncio.sleep(MEMORY_DIAG_SECONDS)
  _mem("watchdog")
async def main():
 poller=asyncio.create_task(polling_loop(),name="telegram-command-poller");heartbeat=asyncio.create_task(status_loop(),name="live-status-heartbeat");goal_watch=asyncio.create_task(fast_goal_watch.loop(),name="fast-goal-watch");betb2b=asyncio.create_task(betb2b_loop(),name="betb2b-market-sampler");marketnode=asyncio.create_task(market_node_loop(),name="remote-market-node");markettest=asyncio.create_task(market_test_loop(),name="market-test-signal");memwatch=asyncio.create_task(memory_watchdog(),name="memory-watchdog")
 logger.info("GOOL LIVE | build=%s | live-only primary | analytics: Flashscore + history/H2H + GOAL API + FotMob + 365Scores + xG context + BETB2B + remote market node | local prematch collector disabled | remote_market_node=%s | market_test=owner-text",BUILD_ID,bool(market_node_bridge.URL));_mem("main_started")
 try:
  while True:
   started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
 finally:
  for task in (poller,heartbeat,goal_watch,betb2b,marketnode,markettest,memwatch):task.cancel()
  await asyncio.gather(poller,heartbeat,goal_watch,betb2b,marketnode,markettest,memwatch,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())
