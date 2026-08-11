"""Persistent JSON journal for GOOL BOT signals and end-of-day evaluation."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

JOURNAL_FILE = Path(os.getenv("SIGNAL_JOURNAL_FILE", "signal_journal.json"))


def _load() -> dict[str, Any]:
    if not JOURNAL_FILE.exists():
        return {"signals": []}
    try:
        data = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"signals": []}
    except Exception:
        return {"signals": []}


def _save(data: dict[str, Any]) -> None:
    data.setdefault("signals", [])
    JOURNAL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_signal(record: dict[str, Any], dedupe_key: str) -> bool:
    data = _load()
    signals = data.setdefault("signals", [])
    if any(str(row.get("dedupe_key")) == dedupe_key for row in signals):
        return False
    row = dict(record)
    row["dedupe_key"] = dedupe_key
    row.setdefault("created_ts", int(time.time()))
    row.setdefault("result", "pending")
    signals.append(row)
    # Keep a long enough history for weekly/monthly analysis without unbounded growth.
    cutoff = int(time.time()) - 90 * 24 * 3600
    data["signals"] = [x for x in signals if int(x.get("created_ts", 0)) >= cutoff]
    _save(data)
    return True


def update_signal(dedupe_key: str, **fields: Any) -> bool:
    data = _load()
    for row in data.setdefault("signals", []):
        if str(row.get("dedupe_key")) == dedupe_key:
            row.update(fields)
            _save(data)
            return True
    return False


def all_signals() -> list[dict[str, Any]]:
    return list(_load().get("signals", []))
