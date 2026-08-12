"""24/7 GOOL runner with Telegram multi-user subscriptions.

LIVE scans run continuously. The owner's PREMATCH delivery remains on GitHub
Actions, while additional Telegram subscribers receive PREMATCH scans from this
24/7 process so they share the same local subscription registry.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOT_DIR = ROOT / "gool_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

os.environ.setdefault("LIVE_SIGNAL_THRESHOLD", "75")
os.environ.setdefault("LIVE_COOLDOWN_MINUTES", "12")

LIVE_INTERVAL_SECONDS = max(30, int(os.getenv("LIVE_INTERVAL_SECONDS", "60")))
PREMATCH_INTERVAL_SECONDS = max(120, int(os.getenv("PREMATCH_INTERVAL_SECONDS", "300")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gool_live_24x7")

import visual_feed_unified_bot  # noqa: E402
import live_candidate_patch  # noqa: E402,F401 - installs multi-logic LIVE gate
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


# GitHub Actions keeps PREMATCH for the owner. On the 24/7 host the same scanner
# is reused only for additional /start subscribers, avoiding duplicate owner alerts.
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
        logger.error("Telegram configuration: INVALID — %s", tg_reason)

    poller = asyncio.create_task(polling_loop(), name="telegram-command-poller")
    prematch = asyncio.create_task(prematch_loop(), name="subscriber-prematch-scanner")
    logger.info("Telegram /start /stop /status polling enabled")
    logger.info(
        "GOOL BOT 24/7 started | LIVE every %ss | subscriber PREMATCH every %ss",
        LIVE_INTERVAL_SECONDS,
        PREMATCH_INTERVAL_SECONDS,
    )

    try:
        while True:
            started = time.monotonic()
            await run_live()
            elapsed = time.monotonic() - started
            await asyncio.sleep(max(2.0, LIVE_INTERVAL_SECONDS - elapsed))
    finally:
        poller.cancel()
        prematch.cancel()
        await asyncio.gather(poller, prematch, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
