"""24/7 runner for lightweight bot-hosting platforms.

Keeps the existing PREMATCH and LIVE analysis code intact while scheduling it
inside one persistent Python process instead of relying on GitHub cron.
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

# Preserve the production thresholds currently used by GitHub Actions.
os.environ.setdefault("MIN_MINUTES_TO_KICKOFF", "2")
os.environ.setdefault("MAX_MINUTES_TO_KICKOFF", "9")
os.environ.setdefault("MIN_BOOKMAKERS", "3")
os.environ.setdefault("MIN_CONSENSUS", "0.65")
os.environ.setdefault("MIN_MEDIAN_DROP", "8.0")
os.environ.setdefault("MAX_SIGNALS_PER_MATCH", "4")
os.environ.setdefault("LIVE_SIGNAL_THRESHOLD", "75")
os.environ.setdefault("LIVE_COOLDOWN_MINUTES", "12")

LIVE_INTERVAL_SECONDS = max(30, int(os.getenv("LIVE_INTERVAL_SECONDS", "60")))
PREMATCH_INTERVAL_SECONDS = max(60, int(os.getenv("PREMATCH_INTERVAL_SECONDS", "300")))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gool_24x7")

# Import after environment defaults and sys.path are configured.
import prematch_standard_scanner  # noqa: E402
import visual_feed_unified_bot  # noqa: E402


async def run_live() -> None:
    try:
        await visual_feed_unified_bot.unified_bot.scan_live_once()
    except Exception:
        logger.exception("LIVE scan failed; runner will continue")


def run_prematch() -> None:
    try:
        prematch_standard_scanner.base.main()
    except Exception:
        logger.exception("PREMATCH scan failed; runner will continue")


async def main() -> None:
    if not os.getenv("TELEGRAM_BOT_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")

    logger.info(
        "GOOL BOT 24/7 started | LIVE every %ss | PREMATCH every %ss",
        LIVE_INTERVAL_SECONDS,
        PREMATCH_INTERVAL_SECONDS,
    )

    next_live = 0.0
    next_prematch = 0.0
    while True:
        now = time.monotonic()

        if now >= next_live:
            await run_live()
            next_live = time.monotonic() + LIVE_INTERVAL_SECONDS

        if now >= next_prematch:
            await asyncio.to_thread(run_prematch)
            next_prematch = time.monotonic() + PREMATCH_INTERVAL_SECONDS

        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
