"""GOOL 2.0 PREMATCH LAB.

Research-only collector used before wiring prematch context into LIVE decisions.
It reuses the lightweight Flashscore master feed already used by GOOL and the
LSApp odds endpoint validated by the flashscore-football-odds-scraper project.

Goals:
- discover scheduled football matches for a calendar day without Chromium;
- capture the whole available market payload (1X2, totals, BTTS, handicaps, etc.);
- preserve opening/current prices for movement analysis;
- calculate margin-free probabilities for comparable markets;
- write one auditable JSON snapshot that production can later consume.

This module does NOT gate or alter any LIVE signal.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from live_engine import _feed

logger = logging.getLogger("prematch_market_lab")
LSAPP_URL = os.getenv("PREMATCH_LSAPP_URL", "https://global.ds.lsapp.eu/odds/pq_graphql")
DATA_DIR = Path(os.getenv("RUNTIME_DATA_DIR", "/data" if Path("/data").exists() else "."))
TIMEOUT = max(5, int(os.getenv("PREMATCH_ODDS_TIMEOUT", "15")))


@dataclass(frozen=True)
class PrematchEvent:
    event_id: str
    kickoff_ts: int
    home: str
    away: str
    league: str
    country: str = ""
    status: str = ""


def _fields(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in str(raw or "").split("¬"):
        if "÷" in token:
            k, v = token.split("÷", 1)
            if k and k not in out:
                out[k] = v
    return out


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _kickoff_ts(f: dict[str, str]) -> int:
    """Return a plausible event start unix timestamp from Flashscore fields."""
    now = int(time.time())
    for key in ("AD", "AO"):
        value = _int(f.get(key))
        # Football master-feed timestamps are seconds; reject elapsed/status numbers.
        if 1_500_000_000 <= value <= now + 370 * 24 * 3600:
            return value
    return 0


def discover_day(target: date | None = None) -> list[PrematchEvent]:
    target = target or datetime.now().astimezone().date()
    body = _feed("f_1_0_0_en_1") or ""
    if not body:
        logger.warning("PREMATCH master feed unavailable")
        return []

    league = ""
    country = ""
    rows: dict[str, PrematchEvent] = {}
    for chunk in body.split("~"):
        if not chunk:
            continue
        if chunk.startswith("ZA÷"):
            f = _fields(chunk)
            league = (f.get("ZA") or "").strip()
            country = (f.get("ZB") or f.get("ZY") or "").strip()
            continue
        if not chunk.startswith("AA÷"):
            continue
        event_id, sep, rest = chunk[3:].partition("¬")
        if not sep or len(event_id) != 8 or not event_id.isalnum():
            continue
        f = _fields(rest)
        kickoff = _kickoff_ts(f)
        if not kickoff:
            continue
        try:
            event_day = datetime.fromtimestamp(kickoff).astimezone().date()
        except (OSError, OverflowError, ValueError):
            continue
        if event_day != target:
            continue
        home = (f.get("AE") or f.get("CX") or "").strip()
        away = (f.get("AF") or "").strip()
        if not home or not away:
            continue
        rows[event_id] = PrematchEvent(
            event_id=event_id,
            kickoff_ts=kickoff,
            home=home,
            away=away,
            league=league,
            country=country,
            status=f.get("AB", ""),
        )
    return sorted(rows.values(), key=lambda x: (x.kickoff_ts, x.league, x.home))


def fetch_odds(event_id: str) -> dict[str, Any]:
    params = {
        "_hash": "oce",
        "eventId": str(event_id),
        "projectId": "5",
        "geoIpCode": "US",
        "geoIpSubdivisionCode": "USCA",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.flashscore.com/",
    }
    try:
        r = requests.get(LSAPP_URL, params=params, headers=headers, timeout=TIMEOUT)
        if r.ok:
            payload = r.json()
            return payload if isinstance(payload, dict) else {}
        logger.info("PREMATCH_ODDS_HTTP %s %s", event_id, r.status_code)
    except (requests.RequestException, ValueError) as exc:
        logger.info("PREMATCH_ODDS_FAILED %s %s", event_id, exc)
    return {}


def _price(item: dict[str, Any], key: str = "value") -> float | None:
    try:
        value = float(item.get(key))
        return value if value > 1.0 and math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _line(item: dict[str, Any]) -> str | None:
    h = item.get("handicap") or {}
    value = h.get("value") if isinstance(h, dict) else None
    return str(value) if value is not None else None


def normalize_odds(payload: dict[str, Any]) -> list[dict[str, Any]]:
    find = ((payload.get("data") or {}).get("findOddsByEventId") or {}) if isinstance(payload, dict) else {}
    entries = find.get("odds") or []
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        market = str(entry.get("bettingType") or "UNKNOWN")
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        bookmaker_id = entry.get("bookmakerId")
        for item in entry.get("odds") or []:
            if not isinstance(item, dict):
                continue
            current = _price(item, "value")
            opening = _price(item, "opening")
            if current is None and opening is None:
                continue
            selection = item.get("selection")
            participant = item.get("eventParticipantId")
            # HOME_DRAW_AWAY uses null participant for draw in LSApp.
            if market == "HOME_DRAW_AWAY" and selection is None and participant is None:
                selection = "DRAW"
            normalized.append({
                "market": market,
                "scope": scope,
                "bookmaker_id": bookmaker_id,
                "selection": str(selection) if selection is not None else None,
                "participant_id": participant,
                "line": _line(item),
                "opening": opening,
                "current": current,
            })
    return normalized


def fair_probabilities(prices: dict[str, float]) -> dict[str, float]:
    """Remove simple bookmaker overround by proportional normalization."""
    inv = {k: 1.0 / float(v) for k, v in prices.items() if v and float(v) > 1.0}
    total = sum(inv.values())
    if not total:
        return {}
    return {k: round(v / total * 100.0, 2) for k, v in inv.items()}


def price_move(opening: float | None, current: float | None) -> dict[str, float] | None:
    if not opening or not current or opening <= 1 or current <= 1:
        return None
    p0 = 100.0 / opening
    p1 = 100.0 / current
    return {
        "opening": round(opening, 3),
        "current": round(current, 3),
        "raw_probability_open": round(p0, 2),
        "raw_probability_now": round(p1, 2),
        "move_pp": round(p1 - p0, 2),
        "price_change_pct": round((current / opening - 1.0) * 100.0, 2),
    }


def summarize_markets(rows: list[dict[str, Any]]) -> dict[str, Any]:
    market_types = sorted({str(r.get("market")) for r in rows if r.get("market")})
    scopes = sorted({str(r.get("scope")) for r in rows if r.get("scope")})
    books = sorted({str(r.get("bookmaker_id")) for r in rows if r.get("bookmaker_id") is not None})
    moved = []
    for r in rows:
        mv = price_move(r.get("opening"), r.get("current"))
        if mv and abs(mv["move_pp"]) >= 1.0:
            moved.append({**r, "movement": mv})
    moved.sort(key=lambda x: abs(x["movement"]["move_pp"]), reverse=True)
    return {
        "market_types": market_types,
        "scopes": scopes,
        "bookmakers": books,
        "quotes": len(rows),
        "largest_moves": moved[:20],
    }


def collect_day(target: date | None = None, odds_limit: int | None = None) -> dict[str, Any]:
    target = target or datetime.now().astimezone().date()
    events = discover_day(target)
    result: dict[str, Any] = {
        "schema": "GOOL_PREMATCH_LAB_V1",
        "date": target.isoformat(),
        "created_ts": int(time.time()),
        "events_found": len(events),
        "events": [],
    }
    for idx, event in enumerate(events):
        item: dict[str, Any] = asdict(event)
        if odds_limit is None or idx < odds_limit:
            payload = fetch_odds(event.event_id)
            odds = normalize_odds(payload)
            item["markets"] = odds
            item["market_summary"] = summarize_markets(odds)
        result["events"].append(item)
    return result


def save_day(snapshot: dict[str, Any]) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    day = str(snapshot.get("date") or "unknown")
    path = DATA_DIR / f"prematch_lab_{day}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="GOOL 2.0 prematch market diagnostic")
    parser.add_argument("--date", default="", help="YYYY-MM-DD, default today")
    parser.add_argument("--odds-limit", type=int, default=30, help="fetch markets for first N matches; 0 = all")
    args = parser.parse_args()
    target = date.fromisoformat(args.date) if args.date else datetime.now().astimezone().date()
    limit = None if args.odds_limit == 0 else max(0, args.odds_limit)
    snapshot = collect_day(target, limit)
    path = save_day(snapshot)
    with_markets = sum(bool(x.get("markets")) for x in snapshot.get("events") or [])
    print(f"GOOL PREMATCH LAB {target}: matches={snapshot['events_found']} markets_ok={with_markets} saved={path}")
    for row in (snapshot.get("events") or [])[:20]:
        summary = row.get("market_summary") or {}
        print(f"{datetime.fromtimestamp(row['kickoff_ts']).strftime('%H:%M')} | {row['home']} - {row['away']} | {row.get('league','')} | quotes={summary.get('quotes',0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
