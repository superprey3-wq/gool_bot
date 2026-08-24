"""Low-memory diagnostic probe for SofaScore live football.

This module is intentionally standalone and does not affect GOOL signal decisions.
It matches current GOOL live fixtures against SofaScore's live board, then probes
public event endpoints for statistics, incidents, shotmap, graph/momentum and odds.
Designed for a 512 MB VPS: responses are processed one event at a time and discarded.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from difflib import SequenceMatcher
from typing import Any

import requests

logger = logging.getLogger("sofascore_probe")
ROOT = os.getenv("SOFASCORE_ROOT", "https://www.sofascore.com/api/v1")
TIMEOUT = float(os.getenv("SOFASCORE_TIMEOUT", "8"))
# Recent 2026 public clients need browser-origin headers; token can be overridden
# without code changes if SofaScore rotates it.
XRW = os.getenv("SOFASCORE_X_REQUESTED_WITH", "e06c91")
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/137 Mobile Safari/537.36",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/",
    "x-requested-with": XRW,
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
}


def _norm(value: str) -> str:
    s = str(value or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.replace("women", " ").replace("femenil", " ").replace("feminino", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _get(path: str) -> tuple[int, Any, int]:
    url = f"{ROOT.rstrip('/')}/{path.lstrip('/')}"
    started = time.monotonic()
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        ms = int((time.monotonic() - started) * 1000)
        try:
            data = r.json()
        except ValueError:
            data = None
        return r.status_code, data, ms
    except requests.RequestException as exc:
        logger.info("SOFA_HTTP_FAIL %s %s", path, exc)
        return 0, None, int((time.monotonic() - started) * 1000)


def live_events() -> list[dict[str, Any]]:
    code, data, ms = _get("sport/football/events/live")
    logger.info("SOFA_LIVE_BOARD http=%s ms=%s", code, ms)
    if code != 200 or not isinstance(data, dict):
        return []
    rows = data.get("events") or []
    return rows if isinstance(rows, list) else []


def _candidate_score(match, event: dict[str, Any]) -> float:
    h = (event.get("homeTeam") or {}).get("name", "")
    a = (event.get("awayTeam") or {}).get("name", "")
    direct = (_sim(getattr(match, "home", ""), h) + _sim(getattr(match, "away", ""), a)) / 2
    reverse = (_sim(getattr(match, "home", ""), a) + _sim(getattr(match, "away", ""), h)) / 2
    return max(direct, reverse * 0.94)


def match_event(match, events: list[dict[str, Any]], threshold: float = 0.72) -> dict[str, Any] | None:
    best = None
    best_score = 0.0
    for event in events:
        score = _candidate_score(match, event)
        if score > best_score:
            best, best_score = event, score
    if best is None or best_score < threshold:
        return None
    out = dict(best)
    out["_gool_match_score"] = round(best_score, 3)
    return out


def _has_xg(stats: Any) -> bool:
    blob = json.dumps(stats, ensure_ascii=False).lower() if stats is not None else ""
    return "expected goals" in blob or '"xg"' in blob or "expectedgoals" in blob


def _odds_summary(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"markets": 0, "totals": 0, "decimal_prices": 0}
    markets = data.get("markets") or []
    if not isinstance(markets, list):
        markets = []
    totals = 0
    decimal_prices = 0
    examples = []
    for market in markets:
        text = json.dumps(market, ensure_ascii=False).lower()
        if any(x in text for x in ("over", "under", "total")):
            totals += 1
        for key in ("choices", "outcomes", "selections"):
            rows = market.get(key) if isinstance(market, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = row.get("decimalValue", row.get("decimalOdds", row.get("odds")))
                try:
                    f = float(value)
                except (TypeError, ValueError):
                    continue
                if f > 1:
                    decimal_prices += 1
                    if len(examples) < 4:
                        examples.append({"name": row.get("name") or row.get("choiceName"), "odd": f})
    return {"markets": len(markets), "totals": totals, "decimal_prices": decimal_prices, "examples": examples}


def probe_event(event_id: int | str) -> dict[str, Any]:
    endpoints = {
        "statistics": f"event/{event_id}/statistics",
        "incidents": f"event/{event_id}/incidents",
        "shotmap": f"event/{event_id}/shotmap",
        "momentum": f"event/{event_id}/graph",
        "odds": f"event/{event_id}/odds/1/all",
    }
    result: dict[str, Any] = {"event_id": event_id}
    for name, path in endpoints.items():
        code, data, ms = _get(path)
        available = code == 200 and isinstance(data, (dict, list))
        item: dict[str, Any] = {"http": code, "available": available, "ms": ms}
        if name == "statistics":
            item["has_xg"] = _has_xg(data)
        elif name == "shotmap" and isinstance(data, dict):
            shots = data.get("shotmap") or data.get("shots") or []
            item["shots"] = len(shots) if isinstance(shots, list) else 0
            item["has_xg"] = _has_xg(data)
        elif name == "momentum" and isinstance(data, dict):
            graph = data.get("graphPoints") or data.get("graph") or []
            item["points"] = len(graph) if isinstance(graph, list) else 0
        elif name == "incidents" and isinstance(data, dict):
            rows = data.get("incidents") or []
            item["incidents"] = len(rows) if isinstance(rows, list) else 0
        elif name == "odds":
            item.update(_odds_summary(data))
        result[name] = item
    return result


def probe_matches(matches) -> list[dict[str, Any]]:
    events = live_events()
    output = []
    for match in matches:
        ev = match_event(match, events)
        base = {
            "gool_event_id": str(getattr(match, "event_id", "")),
            "match": f"{getattr(match, 'home', '')} - {getattr(match, 'away', '')}",
            "league": str(getattr(match, "league", "") or ""),
            "matched": bool(ev),
        }
        if not ev:
            output.append(base)
            logger.info("SOFA_NO_MATCH %s", base["match"])
            continue
        event_id = ev.get("id")
        base.update({
            "sofascore_event_id": event_id,
            "match_score": ev.get("_gool_match_score"),
            "sofa_home": (ev.get("homeTeam") or {}).get("name"),
            "sofa_away": (ev.get("awayTeam") or {}).get("name"),
        })
        base.update(probe_event(event_id))
        output.append(base)
        logger.info("SOFA_PROBE %s", json.dumps(base, ensure_ascii=False, separators=(",", ":")))
    return output


def main() -> int:
    # Import only when used as a CLI to avoid altering normal runtime import order.
    import asyncio
    import visual_feed_unified_bot

    live = asyncio.run(visual_feed_unified_bot.unified_bot.discover_live_matches())
    rows = probe_matches(live)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
