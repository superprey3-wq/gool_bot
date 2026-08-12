"""24/7 GOOL runner used by the Docker deployment in this directory.

LIVE scans run continuously. Telegram /start, /stop and /status are handled by
long polling, and signals are broadcast to all active subscribers.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LIVE_SIGNAL_THRESHOLD", "75")
os.environ.setdefault("LIVE_COOLDOWN_MINUTES", "12")

LIVE_INTERVAL_SECONDS = max(30, int(os.getenv("LIVE_INTERVAL_SECONDS", "60")))
PREMATCH_INTERVAL_SECONDS = max(120, int(os.getenv("PREMATCH_INTERVAL_SECONDS", "300")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gool_live_24x7")

import visual_feed_unified_bot  # noqa: E402
import live_candidate_patch  # noqa: E402,F401 - installs multi-logic LIVE gate
import period_market_patch  # noqa: E402,F401 - separates FT best bet from period goal price
import phase_market_patch  # noqa: E402,F401 - 1H +1/+2 goals, then remainder-of-match markets
import prematch_standard_scanner  # noqa: E402
from telegram_subscribers import get_subscribers, polling_loop  # noqa: E402


def _non_owner_subscribers() -> list[str]:
    owner = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return [chat_id for chat_id in get_subscribers() if chat_id != owner]


def _send_prematch_to_non_owner_subscribers(text: str) -> bool:
    token, _ = visual_feed_unified_bot._telegram_credentials()
    if not token:
        return False
    recipients = _non_owner_subscribers()
    delivered = 0
    for chat_id in recipients:
        if visual_feed_unified_bot._send_text_to_chat(token, chat_id, text):
            delivered += 1
    if recipients:
        logger.info("PREMATCH delivered to %d/%d extra subscribers", delivered, len(recipients))
    return delivered > 0


prematch_standard_scanner.base._telegram_send = _send_prematch_to_non_owner_subscribers


async def run_live() -> None:
    try:
        await visual_feed_unified_bot.unified_bot.scan_live_once()
    except Exception:
        logger.exception("LIVE scan failed; runner will continue")


async def prematch_loop() -> None:
    while True:
        started = time.monotonic()
        if _non_owner_subscribers():
            try:
                await asyncio.to_thread(prematch_standard_scanner.main)
            except Exception:
                logger.exception("PREMATCH scan for subscribers failed; runner will continue")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(10.0, PREMATCH_INTERVAL_SECONDS - elapsed))


async def main() -> None:
    tg_ok, tg_reason = visual_feed_unified_bot.telegram_config_status()
    if tg_ok:
        logger.info("Telegram configuration: OK")
    else:
        logger.warning("Telegram configuration: %s", tg_reason)

    poller = asyncio.create_task(polling_loop(), name="telegram-command-poller")
    prematch = asyncio.create_task(prematch_loop(), name="prematch-subscriber-loop")
    logger.info("Telegram /start /stop /status polling enabled")
    logger.info("GOOL BOT LIVE 24/7 started | every %ss | logic=FULL_MULTI_STRATEGY+REAL_MARKET", LIVE_INTERVAL_SECONDS)

    try:
        while True:
            started = time.monotonic()
            await run_live()
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(2.0, LIVE_INTERVAL_SECONDS - elapsed))
    finally:
        poller.cancel(); prematch.cancel()
        await asyncio.gather(poller, prematch, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
