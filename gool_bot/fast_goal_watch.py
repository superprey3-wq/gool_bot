"""Fast goal watcher for already-issued GOOL entries.

The main CORE scan can take several minutes when 100-200 matches are live. Once an
entry is sent we must not wait for the next full scan to notice the goal. This module
checks only events with a real pending entry, using the lightweight Flashscore summary
endpoint, and schedules the existing VAR-safe green-card confirmation immediately.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import threading
import time
from types import SimpleNamespace

from live_engine import fetch_summary
from signal_journal import all_signals
import score_sync_patch
import telegram_image_signal_patch as tip

logger = logging.getLogger("fast_goal_watch")
INTERVAL_SECONDS = max(15, int(os.getenv("GOAL_WATCH_INTERVAL_SECONDS", "20")))
_PENDING_VALUES = {"", "pending", "wait", "waiting"}


def _score_tuple(value):
    try:
        a, b = str(value or "0:0").split(":", 1)
        return int(a), int(b)
    except Exception:
        return 0, 0


def _pending_entries():
    """Latest pending real LIVE entry per event."""
    latest = {}
    try:
        rows = all_signals()
    except Exception as exc:
        logger.warning("GOAL_WATCH_JOURNAL_FAILED: %s", exc)
        return latest
    for row in rows:
        if row.get("kind") != "live":
            continue
        if str(row.get("reason") or "signal") not in {"signal", "reentry"}:
            continue
        if str(row.get("result") or "pending").strip().lower() not in _PENDING_VALUES:
            continue
        eid = str(row.get("event_id") or "")
        if not eid:
            continue
        old = latest.get(eid)
        if old is None or int(row.get("created_ts", 0) or 0) >= int(old.get("created_ts", 0) or 0):
            latest[eid] = row
    return latest


def _schedule_direct(row, current_score, goal_minute):
    """Create the same candidate used by the normal goal-confirmation path.

    Comparison is against score_at_signal from the persistent journal rather than the
    mutable TRACK score. This avoids missing a goal when a long main scan updates TRACK
    before it reaches Telegram confirmation code.
    """
    eid = str(row.get("event_id") or "")
    before = _score_tuple(row.get("score_at_signal"))
    current = tuple(current_score)
    if not eid or sum(current) <= sum(before):
        return False

    with tip._GOAL_LOCK:
        existing = tip._GOAL_CANDIDATES.get(eid)
        if existing:
            if sum(current) > sum(tuple(existing.get("after") or (0, 0))):
                existing["after"] = current
            return True

        minute = int(goal_minute or row.get("minute") or 0)
        match = SimpleNamespace(
            event_id=eid,
            home=str(row.get("home") or ""),
            away=str(row.get("away") or ""),
            league=str(row.get("league") or ""),
            minute=minute,
            home_score=int(current[0]),
            away_score=int(current[1]),
            is_halftime=False,
        )
        pressure_score = float(row.get("pressure") or row.get("candidate_score") or 0)
        pressure = SimpleNamespace(score=pressure_score, momentum=float(row.get("momentum") or 0), reasons=[])
        primary = row.get("primary")
        recs = [copy.deepcopy(primary)] if isinstance(primary, dict) and primary else []
        master = float(row.get("candidate_score") or row.get("pressure") or pressure_score)
        tip._GOAL_CANDIDATES[eid] = {
            "before": before,
            "after": current,
            "match": match,
            "pressure": pressure,
            "recs": recs,
            "master": master,
            "ts": time.time(),
        }

    logger.warning(
        "FAST_GOAL_DETECTED %s %s — %s | %s -> %s at %s'",
        eid, row.get("home", ""), row.get("away", ""), before, current,
        int(goal_minute or row.get("minute") or 0),
    )
    threading.Thread(
        target=tip._confirm_goal_worker,
        args=(eid,),
        name=f"fast-goal-confirm-{eid}",
        daemon=True,
    ).start()
    return True


def scan_once():
    entries = _pending_entries()
    if not entries:
        return 0
    detected = 0
    for eid, row in entries.items():
        try:
            body = fetch_summary(eid)
            if not body:
                continue
            current, goal_minute = score_sync_patch._summary_state(body)
            if current is None:
                continue
            before = _score_tuple(row.get("score_at_signal"))
            if sum(current) > sum(before):
                if _schedule_direct(row, current, goal_minute):
                    detected += 1
        except Exception as exc:
            logger.info("GOAL_WATCH_FAILED %s: %s", eid, exc)
    if detected:
        logger.info("FAST_GOAL_WATCH scheduled %d confirmation(s)", detected)
    return detected


async def loop():
    logger.info("FAST GOAL WATCH started | pending entries every %ss", INTERVAL_SECONDS)
    while True:
        try:
            await asyncio.to_thread(scan_once)
        except Exception:
            logger.exception("FAST GOAL WATCH iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)
