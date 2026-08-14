"""24/7 GOOL LIVE runner used by Docker deployment."""
from __future__ import annotations
import asyncio,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD","75");os.environ.setdefault("LIVE_COOLDOWN_MINUTES","12")
LIVE_INTERVAL_SECONDS=max(30,int(os.getenv("LIVE_INTERVAL_SECONDS","60")))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");logger=logging.getLogger("gool_live_24x7")
import visual_feed_unified_bot
import live_candidate_patch
import period_market_patch
import phase_market_patch
import market_math_patch  # PREMATCH_MATH stays inside LIVE
import gool_xg_consensus
import telegram_signal_filter_patch
import telegram_image_signal_patch
from telegram_subscribers import polling_loop
import production_logging

async def run_live():
    try:await visual_feed_unified_bot.unified_bot.scan_live_once()
    except Exception:logger.exception("LIVE scan failed; runner will continue")

async def main():
    poller=asyncio.create_task(polling_loop())
    logger.info("GOOL BOT LIVE 24/7 started | every %ss | server PREMATCH loop disabled",LIVE_INTERVAL_SECONDS)
    try:
        while True:
            started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
    finally:
        poller.cancel();await asyncio.gather(poller,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())
