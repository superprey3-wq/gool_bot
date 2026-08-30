"""24/7 GOOL LIVE production runner."""
from __future__ import annotations
import asyncio,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD","80");os.environ.setdefault("LIVE_COOLDOWN_MINUTES","12")
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
import strict_signal_policy_patch
import telegram_image_signal_patch
import analytics_card_fallback_patch
import core_goal_result_card_patch
import entry_sync_failopen_patch
import live_quant_guard_patch
import robust_goal_cooldown_patch
import fast_core_runtime
import signal_journal_runtime_patch
import core_goal_signal_patch
import goal_reset_patch
import core_primary_reconcile
import core_report_truth_patch
import report_journal_detail_patch
import clv_tracker
import live_status_heartbeat
import fast_goal_watch
import core_goal_delivery_reliability_patch
import core_live_stats_reliability_patch
import core_quality_v2_patch
import goal_distribution_v3_runtime
import live_button_patch
import live_button_emergency_patch
import runtime_resource_guard
from telegram_subscribers import polling_loop
import production_logging
# This legacy TOP-load gate is unrelated to V3/Strong Proguz.  Some lightweight
# hosts intentionally do not install aiohttp, so it must never stop MAIN startup.
try:
 import late_premarket_alert_filter_patch
except ModuleNotFoundError as exc:
 if exc.name=="aiohttp":logger.info("LEGACY_TOPLOAD_GATE disabled reason=no_aiohttp")
 else:raise
import remote_strong_proguz_patch
import v3_reporting_patch
runtime_resource_guard.log_startup()
async def run_live():
 try:
  started=time.monotonic();live=await visual_feed_unified_bot.unified_bot.discover_live_matches();discovery=time.monotonic()-started
  # V3 must see the complete Flashscore LIVE pool.  The legacy league gate was
  # built for the retired FIRST_HALF_GOAL / SECOND_HALF_OVER15 strategies and
  # could remove valid early matches before the new bidirectional analyzer saw them.
  score_sync_patch.reuse_once(live)
  sent=await asyncio.to_thread(goal_distribution_v3_runtime.scan,live)
  await asyncio.to_thread(core_primary_reconcile.reconcile,live)
  await asyncio.to_thread(clv_tracker.sample,live)
  logger.info("GOOL_CYCLE_DONE live=%d analyzed=%d v3_sent=%d discovery=%.1fs total=%.1fs full_pool=1",len(live),len(live),sent,discovery,time.monotonic()-started)
 except Exception:logger.exception("LIVE scan failed; runner will continue")
async def status_loop():
 while True:
  await asyncio.sleep(live_status_heartbeat.STATUS_INTERVAL_SECONDS)
  try:await asyncio.to_thread(live_status_heartbeat.send_heartbeat)
  except Exception:logger.exception("LIVE heartbeat failed; runner will continue")
async def resource_loop():
 while True:
  await asyncio.sleep(30);ok,s,reason=runtime_resource_guard.allow_optional()
  logger.info("RESOURCE_WATCH rss=%.1fMB available=%.1fMB load_ratio=%.2f status=%s",s['rss_mb'],s['mem_available_mb'],s['load_ratio'],reason)
async def main():
 poller=asyncio.create_task(polling_loop(),name="telegram-command-poller");heartbeat=asyncio.create_task(status_loop(),name="live-status-heartbeat");goal_watch=asyncio.create_task(fast_goal_watch.loop(),name="fast-goal-watch");resources=asyncio.create_task(resource_loop(),name="resource-watch")
 logger.info("GOOL LIVE | 3 SYSTEMS: FULL MATCH + FIRST HALF + SECOND HALF | V3 exact TOTAL OVER/UNDER | FULL LIVE POOL | odds+value | old CORE/1H/2H delivery=off | BEST BET=off | strong_proguz_relay=on | v3_reports=on")
 try:
  while True:
   started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
 finally:
  for task in (poller,heartbeat,goal_watch,resources):task.cancel()
  await asyncio.gather(poller,heartbeat,goal_watch,resources,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())