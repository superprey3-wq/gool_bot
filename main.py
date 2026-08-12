"""24/7 LIVE-only runner for lightweight bot-hosting platforms.

PREMATCH remains on GitHub Actions, where Chromium is available.
This process only runs the LIVE scanner continuously to keep resource usage low.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gool_live_24x7")

import visual_feed_unified_bot  # noqa: E402
import live_candidate_patch  # noqa: E402,F401 - installs multi-logic LIVE gate


async def run_live() -> None:
    try:
        await visual_feed_unified_bot.unified_bot.scan_live_once()
    except Exception:
        logger.exception("LIVE scan failed; runner will continue")


async def main() -> None:
    tg_ok, tg_reason = visual_feed_unified_bot.telegram_config_status()
    if tg_ok:
        logger.info("Telegram configuration: OK")
    else:
        logger.error("Telegram configuration: INVALID — %s", tg_reason)

    logger.info("GOOL BOT LIVE 24/7 started | every %ss | logic=FULL_MULTI_STRATEGY+REAL_MARKET", LIVE_INTERVAL_SECONDS)

    while True:
        started = time.monotonic()
        await run_live()
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(2.0, LIVE_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    asyncio.run(main())
