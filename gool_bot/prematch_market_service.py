"""GOOL 2.0 rolling PREMATCH market history service.

Continuously discovers today's Flashscore football schedule and stores market
snapshots for every not-yet-started event. The service is deliberately isolated
from signal gating: it observes and records market context only.

Lifecycle per event:
DISCOVERED -> PREMATCH_TRACKING -> FINAL_PREMATCH -> LIVE/FINISHED

Storage is keyed by Flashscore event_id so LIVE can retrieve the exact prematch
history without fuzzy team-name matching.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from typing import Any

from prematch_market_lab import DATA_DIR, PrematchEvent, discover_day, fetch_odds, normalize_odds, summarize_markets

logger = logging.getLogger("prematch_market_service")
DISCOVERY_INTERVAL_SECONDS = max(300, int(os.getenv("PREMATCH_DISCOVERY_INTERVAL_SECONDS", "900")))
ODDS_INTERVAL_SECONDS = max(900, int(os.getenv("PREMATCH_ODDS_INTERVAL_SECONDS", "1800")))
MAX_WORKERS = max(1, min(12, int(os.getenv("PREMATCH_ODDS_WORKERS", "6"))))
START_GRACE_SECONDS = max(0, int(os.getenv("PREMATCH_START_GRACE_SECONDS", "180")))
MAX_SNAPSHOTS_PER_EVENT = max(8, int(os.getenv("PREMATCH_MAX_SNAPSHOTS", "64")))
_LOCK = threading.RLock()


def _path(target: date | None = None) -> Path:
    target = target or datetime.now().astimezone().date()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / f"prematch_history_{target.isoformat()}.json"


def _empty(target: date) -> dict[str, Any]:
    return {
        "schema": "GOOL_PREMATCH_HISTORY_V2",
        "date": target.isoformat(),
        "created_ts": int(time.time()),
        "updated_ts": int(time.time()),
        "events": {},
    }


def _load(target: date | None = None) -> dict[str, Any]:
    target = target or datetime.now().astimezone().date()
    path = _path(target)
    if not path.exists():
        return _empty(target)
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else _empty(target)
    except Exception as exc:
        logger.warning("PREMATCH_HISTORY_READ_FAILED %s", exc)
        return _empty(target)


def _save(data: dict[str, Any], target: date | None = None) -> None:
    target = target or date.fromisoformat(str(data.get("date") or datetime.now().astimezone().date().isoformat()))
    path = _path(target)
    data["updated_ts"] = int(time.time())
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    os.replace(tmp, path)


def _event_meta(event: PrematchEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "kickoff_ts": int(event.kickoff_ts),
        "home": event.home,
        "away": event.away,
        "league": event.league,
        "country": event.country,
        "flashscore_status": event.status,
    }


def _market_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(k) or "") for k in ("market", "scope", "bookmaker_id", "selection", "participant_id", "line"))


def _compact_snapshot(rows: list[dict[str, Any]], captured_ts: int) -> dict[str, Any]:
    # Keep current quotes plus opening/current movement. This is intentionally raw
    # enough for future re-analysis while avoiding the full provider payload.
    normalized = []
    for row in rows:
        normalized.append({
            "k": _market_key(row),
            "market": row.get("market"),
            "scope": row.get("scope"),
            "bookmaker_id": row.get("bookmaker_id"),
            "selection": row.get("selection"),
            "participant_id": row.get("participant_id"),
            "line": row.get("line"),
            "opening": row.get("opening"),
            "current": row.get("current"),
        })
    summary = summarize_markets(rows)
    return {
        "captured_ts": int(captured_ts),
        "quotes": normalized,
        "market_summary": summary,
    }


def _upsert_schedule(target: date, events: list[PrematchEvent]) -> tuple[int, int]:
    with _LOCK:
        data = _load(target)
        store = data.setdefault("events", {})
        created = 0
        changed = 0
        now = int(time.time())
        for event in events:
            eid = str(event.event_id)
            row = store.get(eid)
            if not isinstance(row, dict):
                row = {
                    **_event_meta(event),
                    "discovered_ts": now,
                    "tracking_state": "DISCOVERED",
                    "last_market_ts": 0,
                    "snapshots": [],
                    "final_prematch": None,
                }
                store[eid] = row
                created += 1
            else:
                before = (row.get("kickoff_ts"), row.get("home"), row.get("away"), row.get("league"))
                row.update(_event_meta(event))
                after = (row.get("kickoff_ts"), row.get("home"), row.get("away"), row.get("league"))
                changed += int(before != after)
        _save(data, target)
    return created, changed


def _due_events(target: date) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load(target)
        now = int(time.time())
        out = []
        for row in (data.get("events") or {}).values():
            if not isinstance(row, dict):
                continue
            kickoff = int(row.get("kickoff_ts", 0) or 0)
            if not kickoff:
                continue
            if now >= kickoff + START_GRACE_SECONDS:
                # Freeze the most recent snapshot as final prematch if not already done.
                if row.get("final_prematch") is None:
                    snaps = row.get("snapshots") or []
                    row["final_prematch"] = snaps[-1] if snaps else None
                    row["tracking_state"] = "FINAL_PREMATCH"
                continue
            last = int(row.get("last_market_ts", 0) or 0)
            if not last or now - last >= ODDS_INTERVAL_SECONDS:
                out.append(dict(row))
        _save(data, target)
        return out


def _fetch_one(row: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
    eid = str(row.get("event_id") or "")
    if not eid:
        return "", None, "missing_event_id"
    try:
        payload = fetch_odds(eid)
        odds = normalize_odds(payload)
        if not odds:
            return eid, None, "no_markets"
        return eid, _compact_snapshot(odds, int(time.time())), None
    except Exception as exc:
        return eid, None, type(exc).__name__


def _store_snapshots(target: date, results: list[tuple[str, dict[str, Any] | None, str | None]]) -> tuple[int, int]:
    with _LOCK:
        data = _load(target)
        store = data.setdefault("events", {})
        ok = 0
        failed = 0
        now = int(time.time())
        for eid, snap, error in results:
            row = store.get(str(eid))
            if not isinstance(row, dict):
                continue
            row["last_market_attempt_ts"] = now
            if snap:
                snaps = row.setdefault("snapshots", [])
                snaps.append(snap)
                row["snapshots"] = snaps[-MAX_SNAPSHOTS_PER_EVENT:]
                row["last_market_ts"] = int(snap["captured_ts"])
                row["tracking_state"] = "PREMATCH_TRACKING"
                row["last_market_error"] = None
                ok += 1
            else:
                row["last_market_error"] = error or "unknown"
                failed += 1
        _save(data, target)
        return ok, failed


def collect_once(target: date | None = None) -> dict[str, int]:
    target = target or datetime.now().astimezone().date()
    events = discover_day(target)
    created, changed = _upsert_schedule(target, events)
    due = _due_events(target)
    results: list[tuple[str, dict[str, Any] | None, str | None]] = []
    if due:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="premarket") as pool:
            futures = [pool.submit(_fetch_one, row) for row in due]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    logger.info("PREMATCH_WORKER_FAILED %s", exc)
                # Tiny jitter avoids bursty reconnects when a provider is rate-sensitive.
                time.sleep(random.uniform(0.0, 0.04))
    ok, failed = _store_snapshots(target, results)
    stats = {"events": len(events), "new": created, "changed": changed, "due": len(due), "markets_ok": ok, "markets_failed": failed}
    logger.info("PREMATCH_ROLLING %s", stats)
    return stats


def get_prematch_context(event_id: str, target: date | None = None) -> dict[str, Any] | None:
    """Return the exact prematch dossier for LIVE by Flashscore event_id."""
    eid = str(event_id or "")
    if not eid:
        return None
    targets = [target] if target else [datetime.now().astimezone().date()]
    # Around midnight a LIVE match may have been discovered on the previous day.
    if target is None:
        from datetime import timedelta
        targets.append(targets[0] - timedelta(days=1))
    with _LOCK:
        for day in targets:
            data = _load(day)
            row = (data.get("events") or {}).get(eid)
            if isinstance(row, dict):
                snaps = row.get("snapshots") or []
                return {
                    "event_id": eid,
                    "home": row.get("home"),
                    "away": row.get("away"),
                    "league": row.get("league"),
                    "country": row.get("country"),
                    "kickoff_ts": row.get("kickoff_ts"),
                    "tracking_state": row.get("tracking_state"),
                    "snapshots_count": len(snaps),
                    "first_snapshot": snaps[0] if snaps else None,
                    "latest_snapshot": snaps[-1] if snaps else None,
                    "final_prematch": row.get("final_prematch") or (snaps[-1] if snaps else None),
                }
    return None


async def loop() -> None:
    logger.info(
        "PREMATCH rolling started | discovery=%ss odds=%ss workers=%s data=%s",
        DISCOVERY_INTERVAL_SECONDS, ODDS_INTERVAL_SECONDS, MAX_WORKERS, DATA_DIR,
    )
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(collect_once)
        except Exception:
            logger.exception("PREMATCH rolling iteration failed")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(5.0, DISCOVERY_INTERVAL_SECONDS - elapsed))
