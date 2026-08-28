"""CORE reliability hotfix: explicit live stats + trustworthy post-entry goal baseline.

The 1H engine explicitly fetches/parses Flashscore stats before rendering. CORE used
only discovery objects, which may contain score/minute but no stats. This patch makes
CORE use the same fetch_stats/parse_stats path, synchronizes the journal score/minute
to the exact card that was delivered, and lets the fast goal watcher trust score growth
once that baseline is synchronized.
"""
from __future__ import annotations

import copy
import logging
import time

import fast_goal_watch as fgw
import signal_card as sc
import telegram_image_signal_patch as tip
from live_engine import fetch_stats, parse_stats
from signal_journal import all_signals, update_signal

logger = logging.getLogger("core_live_stats_reliability")
_orig_send_photo_all = tip._send_photo_all
_orig_goal_after_entry = fgw._goal_is_after_entry
_orig_schedule_direct = fgw._schedule_direct


def _latest_core_entry(event_id: str):
    eid = str(event_id or "")
    best = None
    for row in all_signals():
        if row.get("kind") != "live" or str(row.get("event_id") or "") != eid:
            continue
        if str(row.get("reason") or "signal") not in {"signal", "reentry"}:
            continue
        if str(row.get("result") or "pending").strip().lower() not in {"", "pending", "wait", "waiting"}:
            continue
        if best is None or int(row.get("created_ts", 0) or 0) >= int(best.get("created_ts", 0) or 0):
            best = row
    return best


def _with_live_stats(pressure, event_id: str):
    """Attach the same parsed live stats used by FIRST_HALF_GOAL to CORE pressure."""
    parsed = None
    for attempt in range(3):
        try:
            body = fetch_stats(str(event_id))
            if body:
                candidate = parse_stats(body)
                if isinstance(candidate, dict) and candidate:
                    parsed = candidate
                    break
        except Exception as exc:
            logger.info("CORE_STATS_FETCH_FAILED event=%s attempt=%d err=%s", event_id, attempt + 1, exc)
        if attempt < 2:
            time.sleep(0.7)
    if not parsed:
        logger.warning("CORE_STATS_UNAVAILABLE event=%s; preserving existing analytics", event_id)
        return pressure

    try:
        p = copy.copy(pressure)
    except Exception:
        p = pressure

    attached = False
    for attr in ("stats", "raw_stats"):
        try:
            setattr(p, attr, copy.deepcopy(parsed))
            attached = True
        except Exception:
            pass

    try:
        ctx = copy.deepcopy(getattr(p, "analysis_context", None) or {})
        ctx["stats"] = copy.deepcopy(parsed)
        ctx["live_stats"] = copy.deepcopy(parsed)
        setattr(p, "analysis_context", ctx)
        attached = True
    except Exception:
        pass

    if attached:
        try:
            shots = sum(float(x or 0) for x in parsed.get("shots", (0, 0)))
            sot = sum(float(x or 0) for x in parsed.get("shots_on_target", (0, 0)))
            xg = sum(float(x or 0) for x in parsed.get("xg", (0, 0)))
            logger.info("CORE_STATS_SYNC event=%s shots=%g sot=%g xg=%.2f", event_id, shots, sot, xg)
        except Exception:
            logger.info("CORE_STATS_SYNC event=%s keys=%s", event_id, sorted(parsed.keys())[:12])
    return p


def _sync_entry_baseline(match) -> None:
    """Persist the exact score/minute shown on the delivered CORE card."""
    row = _latest_core_entry(getattr(match, "event_id", ""))
    if not row:
        logger.warning("CORE_ENTRY_BASELINE_ROW_MISSING event=%s", getattr(match, "event_id", ""))
        return
    key = str(row.get("dedupe_key") or "")
    if not key:
        return
    score = f"{int(getattr(match, 'home_score', 0) or 0)}:{int(getattr(match, 'away_score', 0) or 0)}"
    minute = int(getattr(match, "minute", 0) or 0)
    if update_signal(key, score_at_signal=score, minute=minute, entry_score_synced=True):
        logger.info("CORE_ENTRY_BASELINE_SYNC event=%s score=%s minute=%d", getattr(match, "event_id", ""), score, minute)


def _send_photo_all(match, pressure, recs, kind, master=None):
    p = pressure
    if kind == "entry":
        p = _with_live_stats(pressure, str(getattr(match, "event_id", "") or ""))
    delivered = _orig_send_photo_all(match, p, recs, kind, master)
    if delivered and kind == "entry":
        _sync_entry_baseline(match)
    return delivered


def _goal_is_after_entry(row, goal_minute):
    # Once score_at_signal was synchronized to the exact delivered card, any later
    # score growth is sufficient proof of a post-entry goal. scan_once/_schedule_direct
    # already require current total goals > score_at_signal total goals.
    if bool(row.get("entry_score_synced")):
        return True
    return _orig_goal_after_entry(row, goal_minute)


def _schedule_direct(row, current_score, goal_minute):
    gm = fgw._int_minute(goal_minute)
    entry = fgw._int_minute(row.get("minute"))
    if bool(row.get("entry_score_synced")) and (not gm or gm <= entry):
        # Some summary variants expose the first/old goal minute even though the score
        # has objectively increased after ENTRY. Use a conservative post-entry minute.
        gm = entry + 1
    return _orig_schedule_direct(row, current_score, gm)


def _compact_sources(names):
    aliases = {"Flashscore": "FS", "GOAL API": "G", "FotMob": "FM", "365Scores": "365", "Form/H2H": "H2H"}
    return " · ".join(aliases.get(str(x), str(x)) for x in names)


tip._send_photo_all = _send_photo_all
fgw._goal_is_after_entry = _goal_is_after_entry
fgw._schedule_direct = _schedule_direct
sc._source_label = _compact_sources

logger.info("CORE reliability patch | explicit stats | synced goal baseline | compact sources")
