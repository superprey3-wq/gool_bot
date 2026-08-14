"""24/7 GOOL runner used by Docker deployment."""
from __future__ import annotations
import asyncio,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD","75");os.environ.setdefault("LIVE_COOLDOWN_MINUTES","12")
LIVE_INTERVAL_SECONDS=max(30,int(os.getenv("LIVE_INTERVAL_SECONDS","60")));PREMATCH_INTERVAL_SECONDS=max(120,int(os.getenv("PREMATCH_INTERVAL_SECONDS","300")))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");logger=logging.getLogger("gool_live_24x7")
import visual_feed_unified_bot
import live_candidate_patch
import period_market_patch
import phase_market_patch
import gool_xg_consensus
import telegram_signal_filter_patch
import telegram_image_signal_patch
import prematch_standard_scanner
from telegram_subscribers import get_subscribers,polling_loop
import production_logging  # final logging profile; GOOL_DEBUG=1 restores diagnostics

def _non_owner_subscribers():
    owner=os.getenv("TELEGRAM_CHAT_ID","").strip();return [x for x in get_subscribers() if x!=owner]
def _send_prematch_to_non_owner_subscribers(text):
    token,_=visual_feed_unified_bot._telegram_credentials()
    if not token:return False
    recipients=_non_owner_subscribers();delivered=0
    for chat_id in recipients:
        if visual_feed_unified_bot._send_text_to_chat(token,chat_id,text):delivered+=1
    if recipients:logger.info("PREMATCH delivered to %d/%d extra subscribers",delivered,len(recipients))
    return delivered>0
prematch_standard_scanner.base._telegram_send=_send_prematch_to_non_owner_subscribers
async def run_live():
    try:await visual_feed_unified_bot.unified_bot.scan_live_once()
    except Exception:logger.exception("LIVE scan failed; runner will continue")
async def prematch_loop():
    while True:
        started=time.monotonic()
        if _non_owner_subscribers():
            try:await asyncio.to_thread(prematch_standard_scanner.main)
            except Exception:logger.exception("PREMATCH scan for subscribers failed; runner will continue")
        await asyncio.sleep(max(10.0,PREMATCH_INTERVAL_SECONDS-(time.monotonic()-started)))
async def main():
    poller=asyncio.create_task(polling_loop());prematch=asyncio.create_task(prematch_loop());logger.info("GOOL BOT LIVE 24/7 started | infographic signals enabled")
    try:
        while True:
            started=time.monotonic();await run_live();await asyncio.sleep(max(2.0,LIVE_INTERVAL_SECONDS-(time.monotonic()-started)))
    finally:
        poller.cancel();prematch.cancel();await asyncio.gather(poller,prematch,return_exceptions=True)
if __name__=="__main__":asyncio.run(main())
