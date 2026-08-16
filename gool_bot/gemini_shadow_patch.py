"""Attach Gemini shadow analysis to real GOOL CORE entries without changing decisions."""
from __future__ import annotations

import logging
import re
import threading

import gemini_shadow
import live_candidate_patch as lc
from live_engine import fetch_stats, parse_stats

logger = logging.getLogger("gemini_shadow_patch")
_original_send = lc._send


def _master(text, pressure):
    m = re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100", text or "")
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    try:
        return float(getattr(pressure, "score", 0) or 0)
    except Exception:
        return 0.0


def _entry_type(text):
    t = text or ""
    if "НОВЫЙ ВХОД ПОСЛЕ ГОЛА" in t:
        return "reentry"
    if "МОЖНО ЗАХОДИТЬ" in t or "МОЖНО РАССМАТРИВАТЬ ВХОД" in t:
        return "signal"
    return None


def _shadow_worker(match, pressure, recs, text, entry_type):
    try:
        body = fetch_stats(str(getattr(match, "event_id", "") or ""))
        stats = parse_stats(body) if body else {}
    except Exception as exc:
        logger.info("GEMINI_SHADOW_STATS_FAILED %s: %s", getattr(match, "event_id", ""), exc)
        stats = {}
    try:
        gemini_shadow.submit(
            match=match,
            pressure=pressure,
            stats=stats,
            recs=recs,
            master=_master(text, pressure),
            route="",
            strategies={},
            market={},
            entry_type=entry_type,
        )
    except Exception:
        logger.exception("GEMINI_SHADOW_SUBMIT_FAILED %s", getattr(match, "event_id", ""))


def _send(match, pressure, recs, text):
    delivered = _original_send(match, pressure, recs, text)
    entry_type = _entry_type(text)
    if delivered and entry_type:
        threading.Thread(
            target=_shadow_worker,
            args=(match, pressure, list(recs or []), text, entry_type),
            name=f"gemini-shadow-hook-{getattr(match, 'event_id', '')}",
            daemon=True,
        ).start()
    return delivered


lc._send = _send
logger.info("Gemini shadow hook enabled: observes CORE entry/reentry only; never blocks signals")
