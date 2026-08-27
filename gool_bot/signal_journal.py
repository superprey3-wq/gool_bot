"""Persistent JSON journal for GOOL BOT signals and end-of-day evaluation.

Writes are serialized and atomic so concurrent LIVE scan / fast goal watcher /
settlement threads cannot overwrite each other's records.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

JOURNAL_FILE = Path(os.getenv("SIGNAL_JOURNAL_FILE", "signal_journal.json"))
_LOCK = threading.RLock()


def _load_unlocked() -> dict[str, Any]:
    if not JOURNAL_FILE.exists():
        return {"signals": []}
    try:
        data = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"signals": []}
    except Exception:
        return {"signals": []}


def _load() -> dict[str, Any]:
    with _LOCK:
        return _load_unlocked()


def _save_unlocked(data: dict[str, Any]) -> None:
    data.setdefault("signals", [])
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOURNAL_FILE.with_name(JOURNAL_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, JOURNAL_FILE)


def _save(data: dict[str, Any]) -> None:
    with _LOCK:
        _save_unlocked(data)


def add_signal(record: dict[str, Any], dedupe_key: str) -> bool:
    # IMPORTANT: load -> mutate -> save must be one critical section. Previously
    # concurrent writers could both load the old file and the later save silently
    # erased a signal written by the other thread.
    with _LOCK:
        data = _load_unlocked()
        signals = data.setdefault("signals", [])
        if any(str(row.get("dedupe_key")) == dedupe_key for row in signals):
            return False
        row = dict(record)
        row["dedupe_key"] = dedupe_key
        row.setdefault("created_ts", int(time.time()))
        row.setdefault("result", "pending")
        signals.append(row)
        cutoff = int(time.time()) - 90 * 24 * 3600
        data["signals"] = [x for x in signals if int(x.get("created_ts", 0)) >= cutoff]
        _save_unlocked(data)
        return True


def update_signal(dedupe_key: str, **fields: Any) -> bool:
    with _LOCK:
        data = _load_unlocked()
        for row in data.setdefault("signals", []):
            if str(row.get("dedupe_key")) == dedupe_key:
                row.update(fields)
                row["updated_ts"] = int(time.time())
                _save_unlocked(data)
                return True
        return False


def all_signals() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_load_unlocked().get("signals", []))
