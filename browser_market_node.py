"""GOOL browser market node.

Dedicated secondary-host collector. No Telegram and no GOOL signal loop.
It uses Playwright Chromium when installed, blocks heavy assets, probes a small
set of public football pages and writes bounded JSON state for later GOOL
market-flow integration.
"""
from __future__ import annotations

import asyncio
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
TIMEOUT_MS = max(5000, int(os.getenv("GOOL_BROWSER_TIMEOUT_MS", "15000")))
TARGETS = [
    ("flashscore", "https://www.flashscore.com/football/"),
    ("oddsportal", "https://www.oddsportal.com/football/"),
]


def _meminfo() -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            out[key] = round(float(raw.strip().split()[0]) / 1024.0, 1)
    except Exception:
        pass
    return out


def _system_browser() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _disk() -> dict[str, float]:
    try:
        u = shutil.disk_usage("/home/container")
        return {"disk_total_mb": round(u.total / 1048576, 1), "disk_free_mb": round(u.free / 1048576, 1)}
    except Exception:
        return {}


async def _collect() -> dict:
    mem = _meminfo()
    state = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "browser",
        "mem_available_mb": mem.get("MemAvailable"),
        "mem_total_mb": mem.get("MemTotal"),
        "poll_seconds": POLL_SECONDS,
        **_disk(),
        "targets": [],
    }
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        state.update(mode="probe", playwright=False, error=f"playwright_import:{type(exc).__name__}")
        return state

    state["playwright"] = True
    system_browser = _system_browser()
    try:
        async with async_playwright() as p:
            launch = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-background-networking"],
            }
            if system_browser:
                launch["executable_path"] = system_browser
            browser = await p.chromium.launch(**launch)
            state["browser"] = system_browser or "playwright-chromium"
            context = await browser.new_context(
                viewport={"width": 1100, "height": 700},
                locale="en-US",
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            )
            page = await context.new_page()

            async def route_handler(route):
                if route.request.resource_type in {"image", "media", "font"}:
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", route_handler)
            for name, url in TARGETS:
                item = {"name": name, "url": url, "ok": False}
                started = time.monotonic()
                try:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
                    item["status"] = response.status if response else None
                    item["title"] = (await page.title())[:160]
                    item["final_url"] = page.url
                    item["html_chars"] = len(await page.content())
                    item["ok"] = bool(response and response.ok)
                except Exception as exc:
                    item["error"] = f"{type(exc).__name__}:{str(exc)[:180]}"
                item["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                state["targets"].append(item)
            await context.close()
            await browser.close()
    except Exception as exc:
        state["browser"] = system_browser or "missing"
        state["browser_error"] = f"{type(exc).__name__}:{str(exc)[:300]}"
    return state


def write_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("GOOL_BROWSER_MARKET_NODE v2 starting telegram=off poll=%ss", POLL_SECONDS)
    while True:
        started = time.monotonic()
        state = asyncio.run(_collect())
        write_state(state)
        good = sum(1 for x in state.get("targets", []) if x.get("ok"))
        LOG.info(
            "BROWSER_CYCLE mode=%s browser=%s targets=%d/%d mem=%sMB disk_free=%sMB error=%s",
            state.get("mode"), state.get("browser", "missing"), good, len(state.get("targets", [])),
            state.get("mem_available_mb"), state.get("disk_free_mb"), state.get("browser_error", "none"),
        )
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
