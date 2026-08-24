"""Shared LIVE exposure and value gates for CORE, HT HUNTER and LATE RISK."""
from __future__ import annotations
from typing import Any

REAL_REASONS = {"signal", "reentry", "ht_hunter", "late_risk"}
PENDING_VALUES = {"", "pending", "wait", "waiting"}
MAX_MATCH_ENTRIES = 2
MAX_OPEN_PER_MATCH = 1


def real_entries(rows: list[dict[str, Any]], event_id: str) -> list[dict[str, Any]]:
    eid = str(event_id or "")
    return [
        r for r in rows
        if r.get("kind") == "live"
        and str(r.get("event_id") or "") == eid
        and str(r.get("reason") or "") in REAL_REASONS
    ]


def can_open(rows: list[dict[str, Any]], event_id: str) -> tuple[bool, str]:
    entries = real_entries(rows, event_id)
    if len(entries) >= MAX_MATCH_ENTRIES:
        return False, f"max_entries={MAX_MATCH_ENTRIES}"
    pending = [r for r in entries if str(r.get("result") or "pending").strip().lower() in PENDING_VALUES]
    if len(pending) >= MAX_OPEN_PER_MATCH:
        return False, f"open_exposure={len(pending)}"
    return True, "ok"


def auditable_primary(primary: dict[str, Any] | None) -> bool:
    if not isinstance(primary, dict):
        return False
    try:
        return bool(primary.get("scope")) and float(primary["line"]) >= 0 and float(primary["odd"]) > 1.0
    except (KeyError, TypeError, ValueError):
        return False


def required_edge(reason: str) -> float:
    reason = str(reason or "signal")
    if reason == "reentry":
        return 7.0
    if reason == "ht_hunter":
        return 7.0
    if reason == "late_risk":
        return 5.0
    return 5.0


def value_ok(primary: dict[str, Any] | None, reason: str) -> tuple[bool, str]:
    if not auditable_primary(primary):
        return False, "primary_not_auditable"
    try:
        edge = float(primary.get("value_edge"))
    except (TypeError, ValueError):
        return False, "edge_missing"
    minimum = required_edge(reason)
    if edge < minimum:
        return False, f"edge={edge:.1f}<{minimum:.1f}"
    return True, "ok"
