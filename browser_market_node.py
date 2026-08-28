"""GOOL lightweight live market collector v5.

Dedicated market-data node. No Telegram, no GOOL signal loop, no browser.
Discovers Flashscore events, pulls LSApp event odds, normalizes markets, and
keeps bounded short history for price-flow diagnostics.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

LOG = logging.getLogger("gool.light_market_node")

STATE_PATH = Path(os.getenv("GOOL_MARKET_STATE", "market_node_state.json"))
HISTORY_PATH = Path(os.getenv("GOOL_MARKET_HISTORY", "market_node_history.json"))
POLL_SECONDS = max(60, int(os.getenv("GOOL_MARKET_POLL_SECONDS", "60")))
TIMEOUT = max(5, int(os.getenv("GOOL_HTTP_TIMEOUT", "15")))
MAX_EVENTS = max(10, min(100, int(os.getenv("GOOL_MARKET_MAX_EVENTS", "60"))))
MAX_ODDS_EVENTS = max(4, min(24, int(os.getenv("GOOL_MARKET_ODDS_EVENTS", "12"))))
MAX_RECORDS = max(200, min(2500, int(os.getenv("GOOL_MARKET_MAX_RECORDS", "1200"))))
HISTORY_DEPTH = max(3, min(12, int(os.getenv("GOOL_MARKET_HISTORY_DEPTH", "8"))))
HISTORY_KEYS = max(300, min(4000, int(os.getenv("GOOL_MARKET_HISTORY_KEYS", "2500"))))

FLASH_PAGE = "https://www.flashscore.com/football/"
ODDS_PAGE = "https://www.oddsportal.com/football/"
FLASH_FEED = "https://local-global.flashscore.ninja/2/x/feed/f_1_0_3_en_1"
LSAPP_BASE = "https://global.ds.lsapp.eu/odds/pq_graphql"

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
LSAPP_HEADERS = {
    **BASE_HEADERS,
    "Referer": "https://www.flashscore.com/",
    "Origin": "https://www.flashscore.com",
    "Accept": "application/json,text/plain,*/*",
}

BOOKMAKERS = {
    16: "bet365",
    21: "Betfred",
    26: "Betway",
    28: "Ladbrokes",
    263: "BetUK",
    429: "Betfair",
    625: "Unibet",
    707: "BetMGM",
    841: "Midnite",
    895: "7Bet",
}

MARKET_NAMES = {
    "HOME_DRAW_AWAY": "1X2",
    "OVER_UNDER": "TOTAL",
    "ASIAN_HANDICAP": "ASIAN_HANDICAP",
    "BOTH_TEAMS_TO_SCORE": "BTTS",
    "DOUBLE_CHANCE": "DOUBLE_CHANCE",
    "DRAW_NO_BET": "DNB",
    "HALF_FULL_TIME": "HT_FT",
    "CORRECT_SCORE": "CORRECT_SCORE",
    "ODD_OR_EVEN": "ODD_EVEN",
    "EUROPEAN_HANDICAP": "EUROPEAN_HANDICAP",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    events = []
    for r in rows:
        event_id = r.get("AA")
        if not event_id:
            continue
        events.append(
            {
                "source": "flashscore",
                "event_id": str(event_id),
                "home": r.get("AE") or r.get("CX") or "",
                "away": r.get("AF") or r.get("CX_2") or "",
                "home_score": r.get("AG"),
                "away_score": r.get("AH"),
                "status": r.get("AC"),
                "start_ts": r.get("AD") or r.get("AB"),
                "raw": {k: r[k] for k in list(r)[:28]},
            }
        )
        if len(events) >= MAX_EVENTS:
            break
    return events


def _event_priority(event):
    hs, aw, status = event.get("home_score"), event.get("away_score"), str(event.get("status") or "")
    scored = int(hs not in (None, "")) + int(aw not in (None, ""))
    live_hint = int(any(ch.isdigit() for ch in status) or status.lower() in {"live", "ht", "1st", "2nd"})
    return (live_hint, scored)


def _oddsportal_links(html):
    links, seen = [], set()
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


def _lsapp_url(event_id):
    return LSAPP_BASE + "?" + urlencode(
        {
            "_hash": "oce",
            "eventId": str(event_id),
            "projectId": 5,
            "geoIpCode": "US",
            "geoIpSubdivisionCode": "USCA",
        }
    )


def _float(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except Exception:
        return None


def _participant_order(items):
    order = []
    for item in items or []:
        pid = item.get("eventParticipantId")
        if pid is not None and pid not in order:
            order.append(pid)
    return order


def _selection_side(entry, item, participant_order):
    btype = str(entry.get("bettingType") or "")
    pid = item.get("eventParticipantId")
    selection = item.get("selection")
    if btype == "HOME_DRAW_AWAY":
        if pid is None:
            return "DRAW"
        if participant_order and pid == participant_order[0]:
            return "HOME"
        if len(participant_order) > 1 and pid == participant_order[1]:
            return "AWAY"
    if btype in {"DRAW_NO_BET", "ASIAN_HANDICAP", "EUROPEAN_HANDICAP"}:
        if participant_order and pid == participant_order[0]:
            return "HOME"
        if len(participant_order) > 1 and pid == participant_order[1]:
            return "AWAY"
    if btype == "OVER_UNDER" and selection is not None:
        return str(selection).upper()
    if btype == "BOTH_TEAMS_TO_SCORE":
        value = item.get("bothTeamsToScore")
        if value is not None:
            return "YES" if bool(value) else "NO"
    for key in ("doubleChance", "correctScore", "oddOrEven", "selection"):
        if item.get(key) not in (None, ""):
            return str(item.get(key)).upper()
    if pid is not None:
        return f"PARTICIPANT:{pid}"
    return "UNKNOWN"


def _normalize_odds(event, payload, ts):
    out = []
    find = (payload or {}).get("data", {}).get("findOddsByEventId", {})
    entries = find.get("odds", []) or []
    for entry in entries:
        bookmaker_id = entry.get("bookmakerId")
        market_raw = str(entry.get("bettingType") or "UNKNOWN")
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        market = MARKET_NAMES.get(market_raw, market_raw)
        items = entry.get("odds", []) or []
        porder = _participant_order(items)
        for item in items:
            if item.get("active") is False:
                continue
            odd = _float(item.get("value"))
            opening = _float(item.get("opening"))
            if odd is None or odd <= 1.0 or odd > 1000:
                continue
            handicap = item.get("handicap") or {}
            line = handicap.get("value") if isinstance(handicap, dict) else None
            line_f = _float(line)
            side = _selection_side(entry, item, porder)
            out.append(
                {
                    "event_id": event.get("event_id"),
                    "home": event.get("home"),
                    "away": event.get("away"),
                    "score": f"{event.get('home_score') or ''}:{event.get('away_score') or ''}",
                    "status": event.get("status"),
                    "bookmaker_id": bookmaker_id,
                    "bookmaker": BOOKMAKERS.get(bookmaker_id, f"book_{bookmaker_id}"),
                    "market": market,
                    "market_raw": market_raw,
                    "scope": scope,
                    "line": line_f,
                    "side": side,
                    "odd": odd,
                    "opening": opening,
                    "timestamp": ts,
                    "source": "flashscore_lsapp",
                }
            )
            if len(out) >= MAX_RECORDS:
                return out
    return out


def _load_history():
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _history_key(r):
    return "|".join(
        [
            str(r.get("event_id") or ""),
            str(r.get("bookmaker_id") or ""),
            str(r.get("market_raw") or r.get("market") or ""),
            str(r.get("scope") or ""),
            str(r.get("line") if r.get("line") is not None else ""),
            str(r.get("side") or ""),
        ]
    )


def _flow_metrics(history_rows, current):
    prev = history_rows[-1] if history_rows else None
    odd = float(current["odd"])
    opening = current.get("opening")
    delta = round(odd - float(prev["odd"]), 4) if prev and prev.get("odd") else None
    pct = round((odd / float(prev["odd"]) - 1.0) * 100.0, 3) if prev and prev.get("odd") else None
    opening_delta = round(odd - float(opening), 4) if opening else None
    velocity = None
    if prev and prev.get("ts") and prev.get("odd"):
        try:
            dt = max(1.0, datetime.fromisoformat(current["timestamp"]).timestamp() - float(prev["ts"]))
            velocity = round(((odd / float(prev["odd"])) - 1.0) * 100.0 / (dt / 60.0), 3)
        except Exception:
            pass

    signs = []
    seq = history_rows[-3:] + [{"odd": odd}]
    for a, b in zip(seq, seq[1:]):
        try:
            d = float(b["odd"]) - float(a["odd"])
            signs.append(1 if d > 0 else -1 if d < 0 else 0)
        except Exception:
            pass
    nonzero = [s for s in signs if s]
    persistence = len(nonzero) >= 2 and len(set(nonzero[-2:])) == 1
    reversal = len(nonzero) >= 2 and nonzero[-1] != nonzero[-2]
    direction = "DOWN" if delta is not None and delta < 0 else "UP" if delta is not None and delta > 0 else "FLAT"

    return {
        "delta": delta,
        "delta_pct": pct,
        "opening_delta": opening_delta,
        "velocity_pct_per_min": velocity,
        "direction": direction,
        "persistence": persistence,
        "reversal": reversal,
        "samples_before": len(history_rows),
    }


def _apply_history(records):
    history = _load_history()
    now_epoch = time.time()
    touched = []
    for r in records:
        key = _history_key(r)
        rows = history.get(key)
        if not isinstance(rows, list):
            rows = []
        r["flow"] = _flow_metrics(rows, r)
        rows.append({"ts": now_epoch, "odd": r["odd"]})
        history[key] = rows[-HISTORY_DEPTH:]
        touched.append(key)

    if len(history) > HISTORY_KEYS:
        ranked = sorted(
            history.items(),
            key=lambda kv: float((kv[1] or [{}])[-1].get("ts", 0) or 0),
            reverse=True,
        )
        history = dict(ranked[:HISTORY_KEYS])

    tmp = HISTORY_PATH.with_suffix(HISTORY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    tmp.replace(HISTORY_PATH)
    return records


def _fetch_event_odds(lib, events):
    records, probes = [], []
    chosen = sorted(events, key=_event_priority, reverse=True)[:MAX_ODDS_EVENTS]
    ts = _now_iso()
    for event in chosen:
        response = _get(lib, _lsapp_url(event["event_id"]), LSAPP_HEADERS)
        probe = {
            "event_id": event["event_id"],
            "home": event.get("home"),
            "away": event.get("away"),
            "status": response.get("status"),
            "ok": response.get("ok"),
            "bytes": response.get("bytes"),
            "elapsed_ms": response.get("elapsed_ms"),
        }
        if response.get("error"):
            probe["error"] = response["error"]
        if response.get("ok"):
            try:
                payload = json.loads(response.get("body") or "{}")
                parsed = _normalize_odds(event, payload, ts)
                records.extend(parsed)
                probe["records"] = len(parsed)
                find = payload.get("data", {}).get("findOddsByEventId", {})
                probe["entries"] = len(find.get("odds", []) or [])
            except Exception as exc:
                probe["parse_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
        probes.append(probe)
        if len(records) >= MAX_RECORDS:
            break
        time.sleep(0.12)
    return _apply_history(records[:MAX_RECORDS]), probes


def _market_summary(records):
    books = {r["bookmaker"] for r in records}
    events = {r["event_id"] for r in records}
    markets = {}
    movers = []
    for r in records:
        markets[r["market"]] = markets.get(r["market"], 0) + 1
        flow = r.get("flow") or {}
        if flow.get("delta_pct") is not None and abs(float(flow["delta_pct"])) >= 0.8:
            movers.append(
                {
                    "event_id": r["event_id"],
                    "bookmaker": r["bookmaker"],
                    "market": r["market"],
                    "scope": r["scope"],
                    "line": r["line"],
                    "side": r["side"],
                    "odd": r["odd"],
                    "delta_pct": flow["delta_pct"],
                    "direction": flow["direction"],
                    "persistence": flow["persistence"],
                    "reversal": flow["reversal"],
                }
            )
    movers.sort(key=lambda x: abs(float(x["delta_pct"])), reverse=True)
    return {
        "records": len(records),
        "events_priced": len(events),
        "bookmakers": len(books),
        "markets": markets,
        "top_movers": movers[:20],
    }


def collect():
    client_name, lib = _client()
    fs_page = _get(lib, FLASH_PAGE)
    op_page = _get(lib, ODDS_PAGE)
    fs_feed = _get(lib, FLASH_FEED, FLASH_HEADERS)

    rows = _decode_flash_feed(fs_feed.get("body", "")) if fs_feed.get("ok") else []
    events = _flash_events(rows)
    op_links = _oddsportal_links(op_page.get("body", "")) if op_page.get("ok") else []
    odds_records, odds_probes = _fetch_event_odds(lib, events) if events else ([], [])
    summary = _market_summary(odds_records)

    return {
        "ts": _now_iso(),
        "version": 5,
        "mode": "http-live-market-flow",
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
        "oddsportal": {"match_links": op_links},
        "lsapp": {
            "events_requested": len(odds_probes),
            "probes": odds_probes,
            "records": odds_records,
            "summary": summary,
        },
    }


def write_state(state):
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def main():
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    LOG.info(
        "GOOL_LIGHT_MARKET_NODE v5 starting telegram=off browser=off poll=%ss odds_events=%d",
        POLL_SECONDS,
        MAX_ODDS_EVENTS,
    )
    while True:
        started = time.monotonic()
        state = collect()
        write_state(state)
        src = state["sources"]
        sm = state["lsapp"]["summary"]
        ok_odds = sum(1 for x in state["lsapp"]["probes"] if x.get("ok"))
        LOG.info(
            "MARKET_V5 flash_feed=%s decoded=%d events=%d lsapp=%d/%d priced_events=%d records=%d books=%d oddsportal_links=%d mem=%sMB",
            src["flashscore_feed"].get("status", src["flashscore_feed"].get("error", "ERR")),
            state["flashscore"]["decoded_rows"],
            len(state["flashscore"]["events"]),
            ok_odds,
            state["lsapp"]["events_requested"],
            sm["events_priced"],
            sm["records"],
            sm["bookmakers"],
            len(state["oddsportal"]["match_links"]),
            state.get("mem_available_mb"),
        )
        if sm["top_movers"]:
            m = sm["top_movers"][0]
            LOG.info(
                "MARKET_MOVE event=%s book=%s market=%s %s %s odd=%.3f delta=%+.2f%% persist=%s reversal=%s",
                m["event_id"],
                m["bookmaker"],
                m["market"],
                m["side"],
                m["line"],
                m["odd"],
                m["delta_pct"],
                m["persistence"],
                m["reversal"],
            )
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
