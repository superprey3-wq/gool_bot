"""Self-contained fallback for Telegram in-game status and runtime version check."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import logging

import telegram_subscribers as ts
from signal_journal import all_signals
from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15

logger = logging.getLogger("live_button_emergency_patch")
MOSCOW = ZoneInfo("Europe/Moscow")
BUILD_ID = "GOOL-2026-08-25-LIVEFIX-2"
_PENDING = {"", "pending", "wait", "waiting"}


def _pending(row):
    sr = str(row.get("signal_result") or "").strip().lower()
    if sr and sr not in _PENDING:
        return False
    return str(row.get("result") or "pending").strip().lower() in _PENDING


def _rows():
    latest = {}
    for row in all_signals():
        if row.get("kind") != "live" or not _pending(row):
            continue
        engine = str(row.get("engine") or "core")
        reason = str(row.get("reason") or "signal")
        if engine not in {FIRST_HALF_GOAL, SECOND_HALF_OVER15} and reason not in {"signal", "reentry"}:
            continue
        eid = str(row.get("event_id") or "")
        if not eid:
            continue
        key = f"{engine}:{eid}"
        try:
            created = float(row.get("created_ts", 0) or 0)
        except (TypeError, ValueError):
            created = 0.0
        old = latest.get(key)
        if old is None or created >= float(old.get("created_ts", 0) or 0):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: float(r.get("created_ts", 0) or 0), reverse=True)


def _label(row):
    engine = str(row.get("engine") or "core")
    if engine == FIRST_HALF_GOAL:
        return "1T · ГОЛ"
    if engine == SECOND_HALF_OVER15:
        return "2T · 2+ ГОЛА"
    return "CORE · ГОЛ"


def _text(rows):
    if not rows:
        return f"🟢 <b>В ИГРЕ</b>\n\nСейчас незакрытых сигналов нет.\n\n<code>{BUILD_ID}</code>"
    lines = [f"🟢 <b>В ИГРЕ — {len(rows)}</b>", "<i>Незакрытые аналитические сигналы из журнала GOOL.</i>", ""]
    for row in rows[:20]:
        try:
            when = datetime.fromtimestamp(int(row.get("created_ts", 0)), MOSCOW).strftime("%H:%M")
        except Exception:
            when = "—"
        minute = row.get("minute")
        minute_txt = f"{minute}'" if minute is not None else "—"
        lines.append(
            f"⏳ <b>{row.get('home')} — {row.get('away')}</b>\n"
            f"↳ {_label(row)} · вход {minute_txt} · {row.get('score_at_signal') or '—'} · {when}"
        )
    lines += ["", f"<code>{BUILD_ID}</code>"]
    return "\n".join(lines)


def _send_live(chat_id):
    try:
        rows = _rows()
        if not ts._send_reply(chat_id, _text(rows), keyboard=True):
            logger.warning("Emergency IN_GAME Telegram delivery failed chat=%s", chat_id)
    except Exception as exc:
        logger.exception("Emergency IN_GAME failed: %s", exc)
        # This path intentionally has no journal/report/live dependencies.
        ts._send_reply(chat_id, f"🟢 <b>В ИГРЕ</b>\n\nНе удалось прочитать журнал, но обработчик активен.\n<code>{BUILD_ID}</code>")


_orig_handle = ts._handle_message

def _handle_message(message: dict):
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text else ""
    if "@" in command:
        command = command.split("@", 1)[0]
    if command == "/version":
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is not None:
            ts.subscribe(chat_id)
            ts._send_reply(chat_id, f"🧩 GOOL runtime: <code>{BUILD_ID}</code>")
        return
    if command == "/status":
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is not None:
            ts.subscribe(chat_id)
            ts._send_reply(chat_id, f"✅ Подписка активна. Получателей: <b>{len(ts.get_subscribers())}</b>.\n🧩 <code>{BUILD_ID}</code>")
        return
    return _orig_handle(message)


ts._send_live = _send_live
ts._handle_message = _handle_message
logger.info("Emergency in-game handler active build=%s", BUILD_ID)
