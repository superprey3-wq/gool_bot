"""GOOL lightweight market collector.

Dedicated secondary-host collector. No Telegram and no GOOL signal loop.
Uses curl_cffi/requests only: no Chromium, no Playwright browser payloads.
Collects public football pages/endpoints cheaply and writes bounded JSON state
for later GOOL market-flow integration.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger("gool.light_market_node")
STATE_PATH = Path(os.getenv("GOOL_MARKET_STATE", "market_node_state.json"))
POLL_SECONDS = max(60, int(os.getenv("GOOL_MARKET_POLL_SECONDS", "60")))
TIMEOUT = max(5, int(os.getenv("GOOL_HTTP_TIMEOUT", "15")))
TARGETS = [
    ("flashscore", "https://www.flashscore.com/football/"),
    ("oddsportal", "https://www.oddsportal.com/football/"),
]


def _meminfo() -> dict[str, float]:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            out[key] = round(float(raw.strip().split()[0]) / 1024.0, 1)
    except Exception:
        pass
    return out


def _client():
    try:
        from curl_cffi import requests as crequests
        return "curl_cffi", crequests
    except Exception:
        import requests
        return "requests", requests


def _fetch(lib, url: str) -> dict:
    started = time.monotonic()
    item = {"url": url, "ok": False}
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    try:
        kwargs = {"headers": headers, "timeout": TIMEOUT, "allow_redirects": True}
        # curl_cffi can impersonate a modern browser without running Chromium.
        if lib.__name__.startswith("curl_cffi"):
            kwargs["impersonate"] = "chrome"
        r = lib.get(url, **kwargs)
        body = r.text or ""
        item.update(
            ok=200 <= int(r.status_code) < 400,
            status=int(r.status_code),
            final_url=str(getattr(r, "url", url)),
            bytes=len(body.encode("utf-8", errors="ignore")),
            preview=body[:180].replace("\n", " "),
        )
    except Exception as exc:
        item["error"] = f"{type(exc).__name__}:{str(exc)[:220]}"
    item["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return item


def collect() -> dict:
    mem = _meminfo()
    client_name, lib = _client()
    state = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "mode": "http",
        "client": client_name,
        "poll_seconds": POLL_SECONDS,
        "mem_available_mb": mem.get("MemAvailable"),
        "mem_total_mb": mem.get("MemTotal"),
        "targets": [],
    }
    for name, url in TARGETS:
        item = _fetch(lib, url)
        item["name"] = name
        state["targets"].append(item)
    return state


def write_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("GOOL_LIGHT_MARKET_NODE v3 starting telegram=off browser=off poll=%ss", POLL_SECONDS)
    while True:
        started = time.monotonic()
        state = collect()
        write_state(state)
        good = sum(1 for x in state["targets"] if x.get("ok"))
        summary = ", ".join(f"{x['name']}={x.get('status', x.get('error','ERR'))}" for x in state["targets"])
        LOG.info(
            "HTTP_MARKET_CYCLE client=%s targets=%d/%d mem=%sMB %s",
            state.get("client"), good, len(state["targets"]), state.get("mem_available_mb"), summary,
        )
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
