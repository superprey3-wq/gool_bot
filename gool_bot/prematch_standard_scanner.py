"""Run the existing prematch scanner but only for standard football total lines."""
from __future__ import annotations

from typing import Any

import prematch_scanner as base

ALLOWED_LINES = {
    "FULL_TIME": {2.5},
    "FIRST_HALF": {0.5, 1.0},
    "SECOND_HALF": {0.5, 1.0, 1.5},
}

_original_extract = base._extract_signals


def _filtered_extract(entries: list[dict[str, Any]], match):
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        allowed = ALLOWED_LINES.get(scope)
        if not allowed:
            continue

        betting_type = str(entry.get("bettingType") or "")
        if not (betting_type == "OVER_UNDER" or ("TOTAL" in betting_type and "SCORE" not in betting_type)):
            # Keep non-total rows needed by participant mapping for team totals.
            if betting_type == "HOME_DRAW_AWAY":
                filtered.append(entry)
            continue

        kept_items = []
        for item in entry.get("odds") or []:
            if not isinstance(item, dict):
                continue
            handicap = item.get("handicap") or {}
            try:
                line = float(handicap.get("value"))
            except (TypeError, ValueError, AttributeError):
                continue
            if line in allowed:
                kept_items.append(item)

        if kept_items:
            copied = dict(entry)
            copied["odds"] = kept_items
            filtered.append(copied)

    return _original_extract(filtered, match)


base._extract_signals = _filtered_extract

if __name__ == "__main__":
    raise SystemExit(base.main())
