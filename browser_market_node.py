"""GOOL lightweight live market collector v6.

Data-only market node: no Telegram, no browser, no betting actions.
Discovers Flashscore events, pulls LSApp odds for several live candidates,
normalizes only useful liquid markets, and measures movement between real
60-second snapshots. Opening-vs-current is kept as context but is never treated
as a fresh market move.
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
HISTORY_PATH = Path(os.getenv("GOOL_MARKET_HISTORY", "market_node_history_v6.json"))
POLL_SECONDS = max(60, int(os.getenv("GOOL_MARKET_POLL_SECONDS", "60")))
TIMEOUT = max(5, int(os.getenv("GOOL_HTTP_TIMEOUT", "15")))
MAX_EVENTS = max(20, min(100, int(os.getenv("GOOL_MARKET_MAX_EVENTS", "60"))))
MAX_ODDS_EVENTS = max(4, min(24, int(os.getenv("GOOL_MARKET_ODDS_EVENTS", "12"))))
MAX_RECORDS = max(300, min(3000, int(os.getenv("GOOL_MARKET_MAX_RECORDS", "1800"))))
MAX_RECORDS_PER_EVENT = max(80, min(500, int(os.getenv("GOOL_MARKET_PER_EVENT", "260"))))
HISTORY_DEPTH = max(3, min(12, int(os.getenv("GOOL_MARKET_HISTORY_DEPTH", "8"))))
HISTORY_KEYS = max(500, min(5000, int(os.getenv("GOOL_MARKET_HISTORY_KEYS", "3000"))))

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

# Known bookmakers from current Flashscore/LSApp mappings. Unknown books are
# counted diagnostically but not used for flow until their IDs are verified.
BOOKMAKERS = {
    16: "bet365", 21: "Betfred", 26: "Betway", 28: "Ladbrokes",
    263: "BetUK", 429: "Betfair", 625: "Unibet", 707: "BetMGM",
    841: "Midnite", 895: "7Bet",
}

MARKET_NAMES = {
    "HOME_DRAW_AWAY": "1X2",
    "OVER_UNDER": "TOTAL",
    "ASIAN_HANDICAP": "ASIAN_HANDICAP",
    "BOTH_TEAMS_TO_SCORE": "BTTS",
    "DOUBLE_CHANCE": "DOUBLE_CHANCE",
    "DRAW_NO_BET": "DNB",
}
ALLOWED_MARKETS = set(MARKET_NAMES)
ALLOWED_SCOPES = {"FULL_TIME", "FIRST_HALF", "SECOND_HALF"}
MAX_ODD_BY_MARKET = {
    "HOME_DRAW_AWAY": 20.0,
    "OVER_UNDER": 12.0,
    "ASIAN_HANDICAP": 12.0,
    "BOTH_TEAMS_TO_SCORE": 8.0,
    "DOUBLE_CHANCE": 6.0,
    "DRAW_NO_BET": 15.0,
}


def _now_iso():
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
        kwargs = {"headers": headers or BASE_HEADERS, "timeout": TIMEOUT, "allow_redirects": True}
        if lib.__name__.startswith("curl_cffi"):
            kwargs["impersonate"] = "chrome"
        r = lib.get(url, **kwargs)
        body = r.text or ""
        out.update(ok=200 <= int(r.status_code) < 400, status=int(r.status_code),
                   final_url=str(getattr(r, "url", url)),
                   bytes=len(body.encode("utf-8", errors="ignore")), body=body)
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
            sep = "÷" if "÷" in part else "·" if "·" in part else None
            if not sep:
                continue
            key, value = part.split(sep, 1)
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
        eid = r.get("AA")
        if not eid:
            continue
        events.append({
            "source": "flashscore", "event_id": str(eid),
            "home": r.get("AE") or r.get("CX") or "",
            "away": r.get("AF") or r.get("CX_2") or "",
            "home_score": r.get("AG"), "away_score": r.get("AH"),
            "status": r.get("AC"), "start_ts": r.get("AD") or r.get("AB"),
            "raw": {k: r[k] for k in list(r)[:28]},
        })
        if len(events) >= MAX_EVENTS:
            break
    return events


def _event_priority(e):
    status = str(e.get("status") or "").lower()
    has_score = e.get("home_score") not in (None, "") or e.get("away_score") not in (None, "")
    live_hint = any(x in status for x in ("live", "ht", "1st", "2nd")) or any(ch.isdigit() for ch in status)
    return (int(live_hint), int(has_score))


def _oddsportal_links(html):
    links, seen = [], set()
    pats = [r'href=["\']([^"\']*/football/[^"\']+-[A-Za-z0-9]{6,}/?)["\']',
            r'href=["\']([^"\']*/football/[^"\']+/[^"\']+/[^"\']+/)["\']']
    for pat in pats:
        for href in re.findall(pat, html or "", flags=re.I):
            url = urljoin(ODDS_PAGE, href)
            if url in seen or "results" in url.lower():
                continue
            seen.add(url); links.append(url)
            if len(links) >= MAX_EVENTS:
                return links
    return links


def _lsapp_url(event_id):
    return LSAPP_BASE + "?" + urlencode({"_hash": "oce", "eventId": str(event_id),
                                         "projectId": 5, "geoIpCode": "US",
                                         "geoIpSubdivisionCode": "USCA"})


def _float(v):
    try:
        f = float(v)
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


def _selection_side(entry, item, order):
    typ = str(entry.get("bettingType") or "")
    pid = item.get("eventParticipantId")
    sel = item.get("selection")
    if typ == "HOME_DRAW_AWAY":
        if pid is None: return "DRAW"
        if order and pid == order[0]: return "HOME"
        if len(order) > 1 and pid == order[1]: return "AWAY"
    if typ in {"DRAW_NO_BET", "ASIAN_HANDICAP"}:
        if order and pid == order[0]: return "HOME"
        if len(order) > 1 and pid == order[1]: return "AWAY"
    if typ == "OVER_UNDER" and sel is not None:
        return str(sel).upper()
    if typ == "BOTH_TEAMS_TO_SCORE":
        val = item.get("bothTeamsToScore")
        if val is not None: return "YES" if bool(val) else "NO"
    if typ == "DOUBLE_CHANCE":
        val = item.get("doubleChance") or sel
        if val not in (None, ""): return str(val).upper()
    return "UNKNOWN"


def _normalize_odds(event, payload, ts):
    out, unknown_books, skipped = [], set(), 0
    entries = ((payload or {}).get("data", {}).get("findOddsByEventId", {}) or {}).get("odds", []) or []
    for entry in entries:
        bid = entry.get("bookmakerId")
        typ = str(entry.get("bettingType") or "")
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        if typ not in ALLOWED_MARKETS or scope not in ALLOWED_SCOPES:
            continue
        if bid not in BOOKMAKERS:
            if bid is not None: unknown_books.add(str(bid))
            continue
        items = entry.get("odds", []) or []
        order = _participant_order(items)
        for item in items:
            if item.get("active") is False:
                continue
            odd = _float(item.get("value")); opening = _float(item.get("opening"))
            if odd is None or odd <= 1.01 or odd > MAX_ODD_BY_MARKET[typ]:
                skipped += 1; continue
            handicap = item.get("handicap") or {}
            line = _float(handicap.get("value")) if isinstance(handicap, dict) else None
            side = _selection_side(entry, item, order)
            if side == "UNKNOWN":
                skipped += 1; continue
            out.append({
                "event_id": event.get("event_id"), "home": event.get("home"), "away": event.get("away"),
                "score": f"{event.get('home_score') or ''}:{event.get('away_score') or ''}",
                "status": event.get("status"), "bookmaker_id": bid, "bookmaker": BOOKMAKERS[bid],
                "market": MARKET_NAMES[typ], "market_raw": typ, "scope": scope,
                "line": line, "side": side, "odd": odd, "opening": opening,
                "timestamp": ts, "source": "flashscore_lsapp",
            })
            if len(out) >= MAX_RECORDS_PER_EVENT:
                return out, unknown_books, skipped
    return out, unknown_books, skipped


def _history_key(r):
    return "|".join(str(x) for x in (r.get("event_id"), r.get("bookmaker_id"), r.get("market_raw"),
                                      r.get("scope"), r.get("line") if r.get("line") is not None else "", r.get("side")))


def _load_history():
    try:
        d = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _flow_metrics(rows, current):
    prev = rows[-1] if rows else None
    odd = float(current["odd"])
    delta = pct = velocity = None
    if prev and prev.get("odd") and prev.get("ts"):
        try:
            p = float(prev["odd"]); dt = max(1.0, time.time() - float(prev["ts"]))
            # Ignore stale history and impossible jumps; these are not fresh flow.
            if dt <= POLL_SECONDS * 3.5:
                raw_pct = (odd / p - 1.0) * 100.0
                if abs(raw_pct) <= 35.0:
                    delta = round(odd - p, 4); pct = round(raw_pct, 3)
                    velocity = round(raw_pct / (dt / 60.0), 3)
        except Exception:
            pass
    opening = current.get("opening")
    opening_pct = None
    if opening and float(opening) > 1.0:
        try: opening_pct = round((odd / float(opening) - 1.0) * 100.0, 3)
        except Exception: pass
    signs = []
    seq = rows[-3:] + [{"odd": odd}]
    for a, b in zip(seq, seq[1:]):
        try:
            d = float(b["odd"]) - float(a["odd"]); signs.append(1 if d > 0 else -1 if d < 0 else 0)
        except Exception: pass
    nz = [s for s in signs if s]
    return {"delta": delta, "delta_pct": pct, "opening_delta_pct": opening_pct,
            "velocity_pct_per_min": velocity,
            "direction": "DOWN" if pct is not None and pct < 0 else "UP" if pct is not None and pct > 0 else "FLAT",
            "persistence": len(nz) >= 2 and len(set(nz[-2:])) == 1,
            "reversal": len(nz) >= 2 and nz[-1] != nz[-2],
            "samples_before": len(rows)}


def _apply_history(records):
    history = _load_history(); now = time.time()
    for r in records:
        key = _history_key(r); rows = history.get(key) if isinstance(history.get(key), list) else []
        r["flow"] = _flow_metrics(rows, r)
        rows.append({"ts": now, "odd": r["odd"]}); history[key] = rows[-HISTORY_DEPTH:]
    if len(history) > HISTORY_KEYS:
        ranked = sorted(history.items(), key=lambda kv: float((kv[1] or [{}])[-1].get("ts", 0) or 0), reverse=True)
        history = dict(ranked[:HISTORY_KEYS])
    tmp = HISTORY_PATH.with_suffix(HISTORY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8"); tmp.replace(HISTORY_PATH)
    return records


def _fetch_event_odds(lib, events):
    records, probes, unknown = [], [], set()
    chosen = sorted(events, key=_event_priority, reverse=True)[:MAX_ODDS_EVENTS]
    ts = _now_iso()
    for event in chosen:
        response = _get(lib, _lsapp_url(event["event_id"]), LSAPP_HEADERS)
        probe = {"event_id": event["event_id"], "home": event.get("home"), "away": event.get("away"),
                 "status": response.get("status"), "ok": response.get("ok"),
                 "bytes": response.get("bytes"), "elapsed_ms": response.get("elapsed_ms")}
        if response.get("error"): probe["error"] = response["error"]
        if response.get("ok"):
            try:
                payload = json.loads(response.get("body") or "{}")
                parsed, unknown_ids, skipped = _normalize_odds(event, payload, ts)
                unknown.update(unknown_ids); records.extend(parsed)
                find = (payload.get("data", {}).get("findOddsByEventId", {}) or {})
                probe.update(records=len(parsed), entries=len(find.get("odds", []) or []), skipped=skipped)
            except Exception as exc:
                probe["parse_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
        probes.append(probe)
        if len(records) >= MAX_RECORDS: break
        time.sleep(0.10)
    return _apply_history(records[:MAX_RECORDS]), probes, sorted(unknown)


def _market_summary(records):
    books = {r["bookmaker"] for r in records}; events = {r["event_id"] for r in records}; markets = {}; movers = []
    for r in records:
        markets[r["market"]] = markets.get(r["market"], 0) + 1
        f = r.get("flow") or {}
        pct = f.get("delta_pct")
        # A movement needs at least one previous real snapshot.
        if pct is not None and f.get("samples_before", 0) >= 1 and 0.6 <= abs(float(pct)) <= 35.0:
            movers.append({"event_id": r["event_id"], "home": r["home"], "away": r["away"],
                           "bookmaker": r["bookmaker"], "market": r["market"], "scope": r["scope"],
                           "line": r["line"], "side": r["side"], "odd": r["odd"],
                           "delta_pct": pct, "direction": f["direction"],
                           "persistence": f["persistence"], "reversal": f["reversal"]})
    movers.sort(key=lambda x: abs(float(x["delta_pct"])), reverse=True)
    return {"records": len(records), "events_priced": len(events), "bookmakers": len(books),
            "markets": markets, "top_movers": movers[:20]}


def collect():
    client_name, lib = _client()
    fs_page = _get(lib, FLASH_PAGE); op_page = _get(lib, ODDS_PAGE); fs_feed = _get(lib, FLASH_FEED, FLASH_HEADERS)
    rows = _decode_flash_feed(fs_feed.get("body", "")) if fs_feed.get("ok") else []
    events = _flash_events(rows); op_links = _oddsportal_links(op_page.get("body", "")) if op_page.get("ok") else []
    odds_records, probes, unknown = _fetch_event_odds(lib, events) if events else ([], [], [])
    summary = _market_summary(odds_records)
    return {"ts": _now_iso(), "version": 6, "mode": "http-live-market-flow", "client": client_name,
            "poll_seconds": POLL_SECONDS, "mem_available_mb": _mem_available_mb(),
            "sources": {"flashscore_page": {k:v for k,v in fs_page.items() if k != "body"},
                        "oddsportal_page": {k:v for k,v in op_page.items() if k != "body"},
                        "flashscore_feed": {k:v for k,v in fs_feed.items() if k != "body"}},
            "flashscore": {"decoded_rows": len(rows), "events": events},
            "oddsportal": {"match_links": op_links},
            "lsapp": {"events_requested": len(probes), "probes": probes, "records": odds_records,
                      "summary": summary, "unknown_bookmaker_ids": unknown}}


def write_state(state):
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(STATE_PATH)


def main():
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    LOG.info("GOOL_LIGHT_MARKET_NODE v6 starting telegram=off browser=off poll=%ss odds_events=%d", POLL_SECONDS, MAX_ODDS_EVENTS)
    while True:
        started = time.monotonic(); state = collect(); write_state(state)
        src = state["sources"]; sm = state["lsapp"]["summary"]; ok_odds = sum(1 for x in state["lsapp"]["probes"] if x.get("ok"))
        LOG.info("MARKET_V6 flash_feed=%s decoded=%d events=%d lsapp=%d/%d priced_events=%d records=%d books=%d markets=%s unknown_books=%d op_links=%d mem=%sMB",
                 src["flashscore_feed"].get("status", src["flashscore_feed"].get("error", "ERR")),
                 state["flashscore"]["decoded_rows"], len(state["flashscore"]["events"]), ok_odds,
                 state["lsapp"]["events_requested"], sm["events_priced"], sm["records"], sm["bookmakers"],
                 ",".join(f"{k}:{v}" for k,v in sorted(sm["markets"].items())),
                 len(state["lsapp"]["unknown_bookmaker_ids"]), len(state["oddsportal"]["match_links"]), state.get("mem_available_mb"))
        if sm["top_movers"]:
            m = sm["top_movers"][0]
            LOG.info("MARKET_MOVE event=%s %s-%s book=%s market=%s %s %s odd=%.3f delta=%+.2f%% persist=%s reversal=%s",
                     m["event_id"], m["home"], m["away"], m["bookmaker"], m["market"], m["side"], m["line"],
                     m["odd"], m["delta_pct"], m["persistence"], m["reversal"])
        else:
            LOG.info("MARKET_FLOW warming_or_quiet snapshots_needed=2")
        elapsed = time.monotonic() - started; time.sleep(max(1.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    main()
