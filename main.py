"""24/7 GOOL LIVE runner with Telegram multi-user subscriptions."""
from __future__ import annotations
import asyncio,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;BOT_DIR=ROOT/"gool_bot"
if str(BOT_DIR) not in sys.path:sys.path.insert(0,str(BOT_DIR))
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD","75");os.environ.setdefault("LIVE_COOLDOWN_MINUTES","12")
LIVE_INTERVAL_SECONDS=max(30,int(os.getenv("LIVE_INTERVAL_SECONDS","60")))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");logger=logging.getLogger("gool_live_24x7")
import visual_feed_unified_bot
import live_candidate_patch
import halftime_hazard_patch
import period_market_patch
import phase_market_patch
import score_sync_patch
import market_math_patch
import gool_xg_consensus
import telegram_signal_filter_patch
import telegram_image_signal_patch
import live_status_heartbeat
from telegram_subscribers import polling_loop
import production_logging

async def run_live():
    try:await visual_feed_unified_bot.unified_bot.scan_live_once()
    except Exception:logger.exception("LIVE scan failed; runner will continue")

async def status_loop():
    while True:
        await asyncio.sleep(live_status_heartbeat.STATUS_INTERVAL_SECONDS)
        try:await asyncio.to_thread(live_status_heartbeat.send_heartbeat)
        except Exception:logger.exception("LIVE heartbeat failed; runner will continue")

async def main():
    tg_ok,tg_reason=visual_feed_unified_bot.telegram_config_status();logger.info("Telegram configuration: OK" if tg_ok else "Telegram configuration: INVALID — %s",*([] if tg_ok else [tg_reason]))
    poller=asyncio.create_task(polling_loop(),name="telegram-command-poller")
    heartbeat=asyncio.create_task(status_loop(),name="live-status-heartbeat")
    logger.info("GOOL BOT 24/7 started | LIVE every %ss | heartbeat every %ss | server PREMATCH loop disabled",LIVE_INTERVAL_SECONDS,live_status_heartbeat.STATUS_INTERVAL_SECONDS)
    try:
        while True:
            started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
    finally:
        poller.cancel();heartbeat.cancel();await asyncio.gather(poller,heartbeat,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())
