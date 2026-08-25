"""Persistent GOOL 2.0 signal journal with epoch isolation and atomic writes."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

JOURNAL_FILE = Path(os.getenv("SIGNAL_JOURNAL_FILE", "signal_journal.json"))
CURRENT_EPOCH = os.getenv("GOOL_JOURNAL_EPOCH", "GOOL-2.0").strip() or "GOOL-2.0"
MODEL_VERSION = os.getenv("GOOL_MODEL_VERSION", "2.0").strip() or "2.0"
BUILD_ID = os.getenv("GOOL_BUILD_ID", "GOOL-2.0").strip() or "GOOL-2.0"
_LOCK = threading.RLock()
_INITIALIZED = False


def _empty() -> dict[str, Any]:
    return {
        "epoch": CURRENT_EPOCH,
        "model_version": MODEL_VERSION,
        "created_ts": int(time.time()),
        "signals": [],
    }


def _archive_path() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return JOURNAL_FILE.with_name(f"{JOURNAL_FILE.stem}.legacy-{stamp}{JOURNAL_FILE.suffix or '.json'}")


def _atomic_write(data: dict[str, Any]) -> None:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{JOURNAL_FILE.name}.", suffix=".tmp", dir=str(JOURNAL_FILE.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, JOURNAL_FILE)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _ensure_epoch_locked() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if JOURNAL_FILE.exists():
        try:
            existing = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = None
        existing_epoch = existing.get("epoch") if isinstance(existing, dict) else None
        if existing_epoch != CURRENT_EPOCH:
            archive = _archive_path()
            try:
                shutil.copy2(JOURNAL_FILE, archive)
            except OSError:
                # Do not destroy an unreadable/locked legacy journal if backup fails.
                _INITIALIZED = True
                return
            _atomic_write(_empty())
        elif not isinstance(existing.get("signals"), list):
            _atomic_write(_empty())
    else:
        _atomic_write(_empty())
    _INITIALIZED = True


def _load_locked() -> dict[str, Any]:
    _ensure_epoch_locked()
    if not JOURNAL_FILE.exists():
        return _empty()
    try:
        data = json.loads(JOURNAL_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("epoch") == CURRENT_EPOCH:
            data.setdefault("signals", [])
            return data
    except Exception:
        pass
    return _empty()


def _load() -> dict[str, Any]:
    with _LOCK:
        return _load_locked()


def _save_locked(data: dict[str, Any]) -> None:
    data.setdefault("signals", [])
    data["epoch"] = CURRENT_EPOCH
    data["model_version"] = MODEL_VERSION
    _atomic_write(data)


def _save(data: dict[str, Any]) -> None:
    with _LOCK:
        _save_locked(data)


def add_signal(record: dict[str, Any], dedupe_key: str) -> bool:
    with _LOCK:
        data = _load_locked()
        signals = data.setdefault("signals", [])
        if any(str(row.get("dedupe_key")) == dedupe_key for row in signals):
            return False
        row = dict(record)
        row["dedupe_key"] = dedupe_key
        row.setdefault("created_ts", int(time.time()))
        row.setdefault("result", "pending")
        row.setdefault("journal_epoch", CURRENT_EPOCH)
        row.setdefault("model_version", MODEL_VERSION)
        row.setdefault("build_id", BUILD_ID)
        row.setdefault("journal_version", 7)
        signals.append(row)
        cutoff = int(time.time()) - 90 * 24 * 3600
        data["signals"] = [x for x in signals if int(x.get("created_ts", 0) or 0) >= cutoff]
        _save_locked(data)
        return True


def update_signal(dedupe_key: str, **fields: Any) -> bool:
    with _LOCK:
        data = _load_locked()
        for row in data.setdefault("signals", []):
            if str(row.get("dedupe_key")) == dedupe_key:
                row.update(fields)
                row.setdefault("journal_epoch", CURRENT_EPOCH)
                row.setdefault("model_version", MODEL_VERSION)
                row.setdefault("build_id", BUILD_ID)
                row.setdefault("journal_version", 7)
                _save_locked(data)
                return True
        return False


def all_signals() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_load_locked().get("signals", []))


def journal_meta() -> dict[str, Any]:
    with _LOCK:
        data = _load_locked()
        return {
            "epoch": data.get("epoch"),
            "model_version": data.get("model_version"),
            "signals": len(data.get("signals") or []),
            "path": str(JOURNAL_FILE),
        }
