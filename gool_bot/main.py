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
    if line.startswith("VmRSS:"):return round(int(line.split()[1])/1024.0,1)
 except Exception:pass
 return -1.0
def _mem(stage):logger.info("MEM_DIAG stage=%s rss_mb=%.1f",stage,_rss_mb())
import visual_feed_unified_bot
import xg_proxy_patch,live_only_recommendation_patch,live_candidate_patch,candidate_enrichment_patch,scores365_enrichment_patch,deep_stats_consensus_patch,context_adjustment_patch,core_warmup_patch,halftime_hazard_patch,period_market_patch,phase_market_patch,multi_source_odds_patch,live_odds_freshness_patch,btts_period_sources_patch,team_total_sources_patch,sportsgameodds_patch,best_market_selector_patch,score_sync_patch,market_math_patch,gool_xg_consensus,odds_nonblocking_patch,telegram_signal_filter_patch,betb2b_market_signal,market_node_bridge,telegram_image_signal_patch,analytics_card_fallback_patch,live_card_quality_patch,entry_card_delivery_patch,multi_source_core_stats_patch,entry_sync_failopen_patch,live_quant_guard_patch,robust_goal_cooldown_patch,fast_core_runtime,signal_journal_runtime_patch,core_goal_signal_patch,goal_reset_patch,core_primary_reconcile,clv_tracker,live_status_heartbeat,fast_goal_watch,confirmation_integrity_patch,multi_engine_runtime,betb2b_card_patch,aux_score_freshness_patch,multi_source_aux_stats_patch,second_half_strategy_patch,card_explainability_patch,second_half_card_reason_patch,aux_result_minute_patch,release_build_patch
from league_signal_gate import filter_for_multi_engine
import telegram_subscribers,subscriber_persistence_patch,telegram_interactive_live_patch,owner_market_tape_patch,market_test_signal,market_total_results_telegram_patch,market_spike_signal,market_recommendation_results,market_results_telegram_patch,best_bet_engine
from telegram_subscribers import polling_loop,BUILD_ID
import production_logging
import market_test_signal_strict_patch
import market_event_reset_patch
import runtime_resource_guard
_mem("imports_done");runtime_resource_guard.log_startup()
async def run_live():
 try:
  _mem("cycle_start");started=time.monotonic();live=await visual_feed_unified_bot.unified_bot.discover_live_matches();discovery=time.monotonic()-started
  await asyncio.to_thread(market_test_signal.update_live_context,live)
  best_settled=await asyncio.to_thread(best_bet_engine.update_results,live);_mem("after_best_bet_results")
  if best_settled:logger.info("BEST_BET results_sent=%d",best_settled)
  _mem("after_discovery");await asyncio.to_thread(market_recommendation_results.update_from_live,live);score_sync_patch.reuse_once(live);_mem("after_score_sync")
  await visual_feed_unified_bot.unified_bot.scan_live_once();_mem("after_scan_live_once");engine_live=await asyncio.to_thread(filter_for_multi_engine,live);_mem("after_filter_multi_engine")
  await asyncio.to_thread(multi_engine_runtime.scan_engines,engine_live);_mem("after_multi_engine")
  best_sent=await asyncio.to_thread(best_bet_engine.scan,engine_live);_mem("after_best_bet")
  if best_sent:logger.info("BEST_BET batch_sent=%d",best_sent)
  await asyncio.to_thread(core_primary_reconcile.reconcile,live);_mem("after_reconcile");await asyncio.to_thread(clv_tracker.sample,live);_mem("after_clv")
  logger.info("GOOL_CYCLE_DONE live=%d aux=%d best=%d settled=%d discovery=%.1fs total=%.1fs",len(live),len(engine_live),best_sent,best_settled,discovery,time.monotonic()-started)
 except Exception:logger.exception("LIVE scan failed; runner will continue")
async def status_loop():
 while True:
  await asyncio.sleep(live_status_heartbeat.STATUS_INTERVAL_SECONDS)
  try:await asyncio.to_thread(live_status_heartbeat.send_heartbeat)
  except Exception:logger.exception("LIVE heartbeat failed; runner will continue")
async def betb2b_loop():
 while True:
  try:_mem("betb2b_before");await asyncio.to_thread(betb2b_market_signal.sample_live);_mem("betb2b_after")
  except Exception:logger.exception("BETB2B sample failed; runner will continue")
  await asyncio.sleep(BETB2B_INTERVAL_SECONDS)
async def market_node_loop():
 while True:
  if market_node_bridge.URL:
   try:
    _mem("market_node_before");n=await asyncio.to_thread(market_node_bridge.poll_once);_mem("market_node_after")
    if n:
     saved=await asyncio.to_thread(market_recommendation_results.capture_active);h=market_node_bridge.health();logger.info("PROGRUZ_ONLINE events=%d age=%.1fs market_rec_saved=%d",h.get("events",0),max(0.,time.time()-float(h.get("last_ok",time.time()) or time.time())),saved)
   except Exception:logger.exception("Remote market node pull failed; runner will continue")
  await asyncio.sleep(MARKET_NODE_PULL_SECONDS)
async def market_test_loop():
 while True:
  try:
   await asyncio.sleep(3);_mem("market_test_before")
   sent=await asyncio.to_thread(market_test_signal.scan_once);spikes=await asyncio.to_thread(market_spike_signal.scan_once);_mem("market_test_after")
   if sent:logger.info("MARKET_TEST batch_sent=%d",sent)
   if spikes:logger.info("MARKET_SPIKE batch_sent=%d",spikes)
  except Exception:logger.exception("MARKET TEST/SPIKE scan failed; runner will continue")
  await asyncio.sleep(MARKET_NODE_PULL_SECONDS)
async def memory_watchdog():
 while True:
  await asyncio.sleep(MEMORY_DIAG_SECONDS);_mem("watchdog")
  ok,s,reason=runtime_resource_guard.allow_optional()
  if not ok:logger.warning("RESOURCE_GUARD reason=%s rss=%.1fMB available=%.1fMB load_ratio=%.2f",reason,s['rss_mb'],s['mem_available_mb'],s['load_ratio'])
async def main():
 poller=asyncio.create_task(polling_loop(),name="telegram-command-poller");heartbeat=asyncio.create_task(status_loop(),name="live-status-heartbeat");goal_watch=asyncio.create_task(fast_goal_watch.loop(),name="fast-goal-watch");betb2b=asyncio.create_task(betb2b_loop(),name="betb2b-market-sampler");marketnode=asyncio.create_task(market_node_loop(),name="remote-market-node");markettest=asyncio.create_task(market_test_loop(),name="market-test-signal");memwatch=asyncio.create_task(memory_watchdog(),name="memory-watchdog")
 logger.info("GOOL LIVE | build=%s | live-only primary | remote_market_node=%s | BEST BET=on+results+fairvalue+flow | owner total alerts=on+event-reset",BUILD_ID,bool(market_node_bridge.URL));_mem("main_started")
 try:
  while True:
   started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
 finally:
  for task in (poller,heartbeat,goal_watch,betb2b,marketnode,markettest,memwatch):task.cancel()
  await asyncio.gather(poller,heartbeat,goal_watch,betb2b,marketnode,markettest,memwatch,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())