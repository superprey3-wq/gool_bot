"""Verified current in-play totals from Flashscore/LSApp.

LIVE menu:  lobtm -> getLiveOddsBettingTypeMenu
LIVE prices: ole2  -> findLiveOddsForBookmaker

Prematch/odds-comparison operations (oce/ope/ope2) are deliberately NOT used here.
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
    if overview.get("type") != "OVER_UNDER":
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
        "odds": odds,
    }


def fetch_live_odds(event_id: str) -> list[dict[str, Any]]:
    """Return only current LIVE OVER/UNDER markets confirmed by lobtm + ole2."""
    menu = _live_menu(event_id)
    if not menu:
        logger.info("LIVE odds menu unavailable: %s", event_id)
        return []

    live_items = [
        item for item in (menu.get("items") or [])
        if item.get("isActive") is True
        and item.get("bettingType") == "OVER_UNDER"
        and "LIVE" in (item.get("types") or [])
    ]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for item in live_items:
        scope = str(item.get("bettingScope") or "")
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
            market = _live_bookmaker_market(event_id, bid, scope)
            row = _normalise_over_under(event_id, bid, scope, market)
            if row:
                rows.append(row)
    logger.info("LIVE odds %s: %d verified O/U bookmaker-scope rows", event_id, len(rows))
    return rows
