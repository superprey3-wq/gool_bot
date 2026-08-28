"""GOOL browser market node.

Dedicated collector process for a secondary host. It intentionally does not start
Telegram or the main GOOL signal loop. The node probes Chromium/Playwright and
keeps resource use conservative before live collectors are enabled.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("gool.browser_market_node")
STATE_PATH = Path(os.getenv("GOOL_MARKET_STATE", "market_node_state.json"))
POLL_SECONDS = max(60, int(os.getenv("GOOL_MARKET_POLL_SECONDS", "60")))


def _meminfo() -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            kb = float(raw.strip().split()[0])
            out[key] = round(kb / 1024.0, 1)
    except Exception:
        pass
    return out


def _browser_binary() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def probe() -> dict:
    mem = _meminfo()
    browser = _browser_binary()
    try:
        import playwright  # noqa: F401
        playwright_ok = True
    except Exception:
        playwright_ok = False
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "probe",
        "browser_binary": browser,
        "playwright_import": playwright_ok,
        "mem_available_mb": mem.get("MemAvailable"),
        "mem_total_mb": mem.get("MemTotal"),
        "poll_seconds": POLL_SECONDS,
    }


def write_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("GOOL_BROWSER_MARKET_NODE starting telegram=off poll=%ss", POLL_SECONDS)
    while True:
        state = probe()
        write_state(state)
        LOG.info(
            "BROWSER_PROBE playwright=%s browser=%s mem_available=%sMB total=%sMB",
            state["playwright_import"], state["browser_binary"] or "missing",
            state["mem_available_mb"], state["mem_total_mb"],
        )
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
