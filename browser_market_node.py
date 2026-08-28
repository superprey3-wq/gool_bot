"""GOOL lightweight live market collector v4.

Dedicated secondary-host collector. No Telegram, no GOOL signal loop, no browser.
Uses requests/curl_cffi, probes Flashscore's public feed shape and OddsPortal HTML,
and writes bounded normalized JSON for the next market-flow stage.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

LOG = logging.getLogger("gool.light_market_node")
STATE_PATH = Path(os.getenv("GOOL_MARKET_STATE", "market_node_state.json"))
POLL_SECONDS = max(60, int(os.getenv("GOOL_MARKET_POLL_SECONDS", "60")))
TIMEOUT = max(5, int(os.getenv("GOOL_HTTP_TIMEOUT", "15")))
MAX_EVENTS = max(10, min(100, int(os.getenv("GOOL_MARKET_MAX_EVENTS", "60"))))

FLASH_PAGE = "https://www.flashscore.com/football/"
ODDS_PAGE = "https://www.oddsportal.com/football/"
FLASH_FEED = "https://local-global.flashscore.ninja/2/x/feed/f_1_0_3_en_1"

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "*/*",
}
FLASH_HEADERS = {
    **BASE_HEADERS,
    "Referer": "https://www.flashscore.com/",
    "Origin": "https://www.flashscore.com",
    "x-fsign": "SW9D1eZo",
    "Cache-Control": "no-cache",
}


def _mem_available_mb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return round(float(line.split()[1]) / 1024.0, 1)
    except Exception:
        pass
    return None


def _client():
    try:
        from curl_cffi import requests as crequests
        return "curl_cffi", crequests
    except Exception:
        import requests
        return "requests", requests


def _get(lib, url, headers=None):
    started = time.monotonic()
    out = {"url": url, "ok": False, "body": ""}
    try:
        kwargs = {
            "headers": headers or BASE_HEADERS,
            "timeout": TIMEOUT,
            "allow_redirects": True,
        }
        if lib.__name__.startswith("curl_cffi"):
            kwargs["impersonate"] = "chrome"
        r = lib.get(url, **kwargs)
        body = r.text or ""
        out.update(
            ok=200 <= int(r.status_code) < 400,
            status=int(r.status_code),
            final_url=str(getattr(r, "url", url)),
            bytes=len(body.encode("utf-8", errors="ignore")),
            body=body,
        )
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}:{str(exc)[:220]}"
    out["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return out


def _decode_flash_feed(text):
    """Decode Flashscore's compact ~ / ¬ / ÷ feed into generic dictionaries."""
    rows = []
    for item in (text or "").split("~"):
        if not item.strip():
            continue
        row = {}
        for part in item.split("¬"):
            if not part:
                continue
            if "÷" in part:
                key, value = part.split("÷", 1)
            elif "·" in part:
                key, value = part.split("·", 1)
            else:
                continue
            if key in row:
                n = 2
                while f"{key}_{n}" in row:
                    n += 1
                key = f"{key}_{n}"
            row[key] = value
        if row:
            rows.append(row)
    return rows


def _flash_events(rows):
    """Keep match-like records; raw fields stay available for validation."""
    events = []
    for r in rows:
        event_id = r.get("AA")
        if not event_id:
            continue
        home = r.get("AE") or r.get("CX") or ""
        away = r.get("AF") or r.get("CX_2") or ""
        # Known Flashscore compact keys vary slightly by feed version, so keep both
        # normalized best-effort fields and a small raw map for runtime verification.
        event = {
            "source": "flashscore",
            "event_id": event_id,
            "home": home,
            "away": away,
            "home_score": r.get("AG"),
            "away_score": r.get("AH"),
            "status": r.get("AC"),
            "start_ts": r.get("AD") or r.get("AB"),
            "raw": {k: r[k] for k in list(r)[:28]},
        }
        events.append(event)
        if len(events) >= MAX_EVENTS:
            break
    return events


def _oddsportal_links(html):
    links = []
    seen = set()
    patterns = [
        r'href=["\']([^"\']*/football/[^"\']+-[A-Za-z0-9]{6,}/?)["\']',
        r'href=["\']([^"\']*/football/[^"\']+/[^"\']+/[^"\']+/)["\']',
    ]
    for pat in patterns:
        for href in re.findall(pat, html or "", flags=re.I):
            url = urljoin(ODDS_PAGE, href)
            if url in seen or "results" in url.lower():
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= MAX_EVENTS:
                return links
    return links


def collect():
    client_name, lib = _client()
    fs_page = _get(lib, FLASH_PAGE)
    op_page = _get(lib, ODDS_PAGE)
    fs_feed = _get(lib, FLASH_FEED, FLASH_HEADERS)

    rows = _decode_flash_feed(fs_feed.get("body", "")) if fs_feed.get("ok") else []
    events = _flash_events(rows)
    op_links = _oddsportal_links(op_page.get("body", "")) if op_page.get("ok") else []

    state = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": 4,
        "mode": "http-live-discovery",
        "client": client_name,
        "poll_seconds": POLL_SECONDS,
        "mem_available_mb": _mem_available_mb(),
        "sources": {
            "flashscore_page": {k: v for k, v in fs_page.items() if k != "body"},
            "oddsportal_page": {k: v for k, v in op_page.items() if k != "body"},
            "flashscore_feed": {k: v for k, v in fs_feed.items() if k != "body"},
        },
        "flashscore": {
            "decoded_rows": len(rows),
            "events": events,
        },
        "oddsportal": {
            "match_links": op_links,
        },
    }
    return state


def write_state(state):
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("GOOL_LIGHT_MARKET_NODE v4 starting telegram=off browser=off poll=%ss", POLL_SECONDS)
    while True:
        started = time.monotonic()
        state = collect()
        write_state(state)
        src = state["sources"]
        fs_status = src["flashscore_feed"].get("status", src["flashscore_feed"].get("error", "ERR"))
        fp_status = src["flashscore_page"].get("status", "ERR")
        op_status = src["oddsportal_page"].get("status", "ERR")
        LOG.info(
            "MARKET_V4 flash_page=%s flash_feed=%s decoded=%d events=%d oddsportal=%s links=%d mem=%sMB",
            fp_status,
            fs_status,
            state["flashscore"]["decoded_rows"],
            len(state["flashscore"]["events"]),
            op_status,
            len(state["oddsportal"]["match_links"]),
            state.get("mem_available_mb"),
        )
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
