"""Current in-play totals from Flashscore/LSApp with a resilient fallback.

Primary route uses the dedicated LIVE menu/bookmaker endpoints (lobtm + ole2).
If that route returns no usable O/U rows, fall back to the event odds-comparison
payload already used successfully elsewhere in the project, but keep only active
OVER/UNDER rows for the live event. Fallback rows are explicitly tagged so logs
show which source produced the price.
"""
from __future__ import annotations

import logging
import os
from typing import Any
import requests

logger = logging.getLogger("live_odds")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
ROOTS = ("https://2.ds.lsapp.eu/pq_graphql", "https://global.ds.lsapp.eu/pq_graphql")
PROJECT_ID = os.getenv("LIVE_ODDS_PROJECT_ID", "2")
GEO = os.getenv("LIVE_ODDS_GEO", "US")
SUBDIVISION = os.getenv("LIVE_ODDS_SUBDIVISION", "USAZ")
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/plain, */*", "Referer": "https://www.flashscore.com/"}


def _query(params: dict[str, Any]) -> dict[str, Any]:
    for root in ROOTS:
        try:
            response = requests.get(root, params=params, headers=HEADERS, timeout=12)
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
        except (requests.RequestException, ValueError):
            continue
    return {}


def _live_menu(event_id: str) -> dict[str, Any]:
    payload = _query({
        "_hash": "lobtm",
        "eventId": event_id,
        "projectId": PROJECT_ID,
        "geoIpCode": GEO,
        "geoIpSubdivisionCode": SUBDIVISION,
    })
    return (payload.get("data") or {}).get("getLiveOddsBettingTypeMenu") or {}


def _live_bookmaker_market(event_id: str, bookmaker_id: int, scope: str) -> dict[str, Any]:
    payload = _query({
        "_hash": "ole2",
        "eventId": event_id,
        "bookmakerId": bookmaker_id,
        "betType": "OVER_UNDER",
        "betScope": scope,
    })
    return (payload.get("data") or {}).get("findLiveOddsForBookmaker") or {}


def _normalise_over_under(event_id: str, bookmaker_id: int, scope: str, market: dict[str, Any]) -> dict[str, Any] | None:
    overview = market.get("eventOddsOverview") or {}
    if str(overview.get("type") or "") != "OVER_UNDER":
        return None
    odds: list[dict[str, Any]] = []
    for opportunity in overview.get("opportunities") or []:
        handicap = opportunity.get("handicap") or {}
        try:
            line = float(handicap.get("value"))
        except (TypeError, ValueError):
            continue
        for selection, key in (("OVER", "over"), ("UNDER", "under")):
            item = opportunity.get(key) or {}
            if item.get("active") is False or item.get("value") in (None, ""):
                continue
            try:
                value = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            if value <= 1.0:
                continue
            odds.append({
                "selection": selection,
                "value": value,
                "active": True,
                "handicap": {"value": line},
                "source": "LIVE_OLE2",
            })
    if not odds:
        return None
    return {
        "eventId": event_id,
        "bookmakerId": bookmaker_id,
        "bettingType": "OVER_UNDER",
        "bettingScope": scope,
        "hasLiveBettingOffers": True,
        "liveVerified": True,
        "source": "LIVE_OLE2",
        "odds": odds,
    }


def _primary_live_rows(event_id: str) -> list[dict[str, Any]]:
    menu = _live_menu(event_id)
    if not menu:
        return []
    items = menu.get("items") or []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for item in items:
        # LSApp has changed these flags/labels before, so accept active O/U rows
        # even when the auxiliary types list does not literally contain LIVE.
        if item.get("isActive") is False:
            continue
        if str(item.get("bettingType") or "") != "OVER_UNDER":
            continue
        scope = str(item.get("bettingScope") or "FULL_TIME")
        if scope not in {"FIRST_HALF", "SECOND_HALF", "FULL_TIME"}:
            continue
        for bookmaker_id in item.get("bookmakerIds") or []:
            try:
                bid = int(bookmaker_id)
            except (TypeError, ValueError):
                continue
            key = (bid, scope)
            if key in seen:
                continue
            seen.add(key)
            row = _normalise_over_under(event_id, bid, scope, _live_bookmaker_market(event_id, bid, scope))
            if row:
                rows.append(row)
    return rows


def _fallback_current_rows(event_id: str) -> list[dict[str, Any]]:
    """Fallback to the event odds-comparison payload and keep current active O/U rows."""
    try:
        from prematch_scanner import _fetch_event_odds
        raw = _fetch_event_odds(event_id)
    except Exception as exc:
        logger.info("LIVE odds fallback unavailable %s: %s", event_id, exc)
        return []

    rows: list[dict[str, Any]] = []
    for entry in raw or []:
        if str(entry.get("bettingType") or "") != "OVER_UNDER":
            continue
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        if scope not in {"FIRST_HALF", "SECOND_HALF", "FULL_TIME"}:
            continue
        clean = []
        for item in entry.get("odds") or []:
            if not isinstance(item, dict) or item.get("active") is False:
                continue
            if str(item.get("selection") or "").upper() not in {"OVER", "UNDER"}:
                continue
            try:
                value = float(item.get("value"))
                line = float((item.get("handicap") or {}).get("value"))
            except (TypeError, ValueError, AttributeError):
                continue
            if value <= 1.0:
                continue
            copy = dict(item)
            copy["value"] = value
            copy["handicap"] = {"value": line}
            copy["active"] = True
            copy["source"] = "LIVE_FALLBACK_OCE"
            clean.append(copy)
        if clean:
            row = dict(entry)
            row["bettingType"] = "OVER_UNDER"
            row["bettingScope"] = scope
            row["liveVerified"] = False
            row["source"] = "LIVE_FALLBACK_OCE"
            row["odds"] = clean
            rows.append(row)
    return rows


def fetch_live_odds(event_id: str) -> list[dict[str, Any]]:
    rows = _primary_live_rows(event_id)
    if rows:
        logger.info("LIVE odds %s: %d O/U rows via LIVE_OLE2", event_id, len(rows))
        return rows

    fallback = _fallback_current_rows(event_id)
    if fallback:
        logger.info("LIVE odds %s: %d O/U rows via LIVE_FALLBACK_OCE", event_id, len(fallback))
        return fallback

    logger.info("LIVE odds %s: no usable O/U rows from primary or fallback", event_id)
    return []
