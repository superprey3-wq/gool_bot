"""Robust Telegram 'In game' view for all GOOL engines.

Reads the signal journal directly instead of depending on report internals. LIVE
lookup is best-effort: if Flashscore discovery is temporarily unavailable, the
button still returns pending runtime signals instead of an error.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import telegram_subscribers as ts
from signal_journal import all_signals
from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15

logger = logging.getLogger("live_button_patch")
MOSCOW = ZoneInfo("Europe/Moscow")
_PENDING = {"", "pending", "wait", "waiting"}


def _result_pending(row: dict) -> bool:
    signal_result = str(row.get("signal_result") or "").strip().lower()
    if signal_result and signal_result not in _PENDING:
        return False
    return str(row.get("result") or "pending").strip().lower() in _PENDING


def _live_ids_best_effort():
    try:
        import unified_bot
        matches = asyncio.run(unified_bot.discover_live_matches())
        return {str(getattr(m, "event_id", "")) for m in matches}
    except Exception as exc:
        logger.warning("IN_GAME live discovery unavailable; journal fallback used: %s", exc)
        return None


def _core_track_ids():
    try:
        import unified_bot
        state = unified_bot._load_sent()
        return {
            str(k).split(":", 1)[1]
            for k, v in state.items()
            if str(k).startswith("TRACK:") and isinstance(v, dict)
        }
    except Exception as exc:
        logger.warning("IN_GAME TRACK state unavailable: %s", exc)
        return set()


def _active_signal_rows():
    now = time.time()
    live_ids = _live_ids_best_effort()
    track_ids = _core_track_ids()
    latest = {}

    try:
        rows = all_signals()
    except Exception as exc:
        logger.exception("IN_GAME journal read failed: %s", exc)
        return []

    for row in rows:
        if row.get("kind") != "live" or not _result_pending(row):
            continue
        eid = str(row.get("event_id") or "")
        if not eid:
            continue
        try:
            created = float(row.get("created_ts", 0) or 0)
        except (TypeError, ValueError):
            created = 0
        # Hard stale guard if LIVE discovery is unavailable.
        if created and now - created > 4 * 3600:
            continue

        engine = str(row.get("engine") or "core")
        reason = str(row.get("reason") or "signal")
        is_aux = engine in {FIRST_HALF_GOAL, SECOND_HALF_OVER15}
        is_core = not is_aux and reason in {"signal", "reentry"}
        if not (is_aux or is_core):
            continue

        if live_ids is not None and eid not in live_ids:
            continue
        # CORE has an explicit runtime TRACK; use it when available. If TRACK
        # storage is temporarily unavailable, do not make the button fail.
        if is_core and track_ids and eid not in track_ids:
            continue

        key = f"{engine}:{eid}"
        old = latest.get(key)
        if old is None or created >= float(old.get("created_ts", 0) or 0):
            latest[key] = row

    return sorted(
        latest.values(),
        key=lambda r: float(r.get("created_ts", 0) or 0),
        reverse=True,
    )


def _engine_label(row: dict) -> str:
    engine = str(row.get("engine") or "core")
    if engine == FIRST_HALF_GOAL:
        return "1T · ГОЛ"
    if engine == SECOND_HALF_OVER15:
        return "2T · 2+ ГОЛА"
    return "CORE · ГОЛ"


def _live_text(rows):
    if not rows:
        return "🟢 <b>В ИГРЕ</b>\n\nСейчас незакрытых сигналов нет."
    lines = [
        f"🟢 <b>В ИГРЕ — {len(rows)}</b>",
        "<i>Активные аналитические сигналы GOOL.</i>",
        "",
    ]
    for row in rows[:20]:
        try:
            when = datetime.fromtimestamp(int(row.get("created_ts", 0)), MOSCOW).strftime("%H:%M")
        except Exception:
            when = "—"
        minute = row.get("minute")
        minute_txt = f"{minute}'" if minute is not None else "—"
        score = row.get("score_at_signal") or "—"
        lines.append(
            f"⏳ <b>{row.get('home')} — {row.get('away')}</b>\n"
            f"↳ {_engine_label(row)} · вход {minute_txt} · {score} · {when}"
        )
    if len(rows) > 20:
        lines.append(f"\n…и ещё {len(rows)-20}")
    return "\n".join(lines)


def _send_live(chat_id):
    try:
        rows = _active_signal_rows()
        # Always use the stable reply keyboard. Archived per-match image buttons
        # are optional UX and must never make the primary 'In game' action fail.
        ok = ts._send_reply(chat_id, _live_text(rows), keyboard=True)
        if not ok:
            logger.warning("IN_GAME Telegram delivery failed for %s", chat_id)
        else:
            logger.info("IN_GAME list sent to %s rows=%d", chat_id, len(rows))
    except Exception as exc:
        logger.exception("IN_GAME handler failed: %s", exc)
        ts._send_reply(chat_id, "⚠️ Не удалось обновить список. Попробуй ещё раз через несколько секунд.")


ts._active_signal_rows = _active_signal_rows
ts._live_text = _live_text
ts._send_live = _send_live
logger.info("Robust all-engine Telegram 'In game' patch active")
