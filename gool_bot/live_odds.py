"""LIVE-only odds adapter.

The odds-comparison endpoint mixes bookmakers/markets that are not available in-play
with bookmakers that explicitly expose live betting offers.  LIVE messages must never
use the former.  This adapter returns only entries explicitly marked by LSApp as
having live betting offers and only currently active selections.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from prematch_scanner import _fetch_event_odds


def fetch_live_odds(event_id: str) -> list[dict[str, Any]]:
    entries = _fetch_event_odds(event_id)
    live_entries: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("hasLiveBettingOffers") is not True:
            continue
        items = entry.get("odds") or []
        active_items = [x for x in items if isinstance(x, dict) and x.get("active", True)]
        if not active_items:
            continue
        row = deepcopy(entry)
        row["odds"] = active_items
        live_entries.append(row)
    return live_entries
