"""Owner-only compact LIVE market movement report for Telegram.

Adds a small `📈 Линия LIVE` button only for the configured owner chat.  The
report is deliberately compact: one row per active GOOL signal, using the
strongest whitelisted market movement already supplied by the secondary node.
It does not alter signal eligibility or probabilities.
"""
from __future__ import annotations

import html
import logging

import telegram_subscribers as tg
import market_node_bridge as bridge

logger = logging.getLogger("owner_market_tape_patch")
_BUTTON = "📈 Линия LIVE"
_orig_keyboard = tg._main_keyboard
_orig_handle_message = tg._handle_message


def _owner(chat_id) -> bool:
    return str(chat_id) == str(tg._owner_chat_id())


def _main_keyboard():
    kb = _orig_keyboard()
    try:
        # Reply keyboards cannot be rendered differently per recipient, so the
        # global keyboard stays unchanged.  The owner gets the private button
        # attached to owner-only replies below.
        return kb
    except Exception:
        return kb


def _owner_keyboard():
    kb = _orig_keyboard()
    rows = list(kb.get("keyboard") or [])
    if not any(any(str(btn.get("text")) == _BUTTON for btn in row if isinstance(btn, dict)) for row in rows):
        rows.append([{"text": _BUTTON}])
    return {"keyboard": rows, "resize_keyboard": True}


def _safe(v, default="—"):
    if v is None or v == "":
        return default
    return html.escape(str(v))


def _short_market(name: str) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        return "рынок без движения"
    return text if len(text) <= 42 else text[:39] + "…"


def _market_line(row: dict) -> str:
    home = str(row.get("home") or "?")
    away = str(row.get("away") or "?")
    minute = row.get("minute")
    try:
        diag = bridge.diagnostic_for_match(home, away)
    except Exception:
        logger.exception("OWNER_MARKET_TAPE diag failed for %s - %s", home, away)
        diag = {}
    dot = str(diag.get("final_dot") or "⚪")
    market = _short_market(diag.get("remote_market") or "")
    try:
        delta = float(diag.get("remote_delta", 0) or 0)
    except Exception:
        delta = 0.0
    try:
        strength = float(diag.get("remote_strength", 0) or 0)
    except Exception:
        strength = 0.0
    mode = str(diag.get("match_mode") or "none")
    minute_txt = f"{minute}'" if minute is not None else "LIVE"
    move = f"{delta:+.2f} п.п." if abs(delta) >= 0.01 else "без заметного сдвига"
    extra = f" · сила {strength:.1f}" if strength else ""
    if mode == "none":
        return f"⚪ <b>{_safe(home)} — {_safe(away)}</b> · {minute_txt}\n↳ рынок пока не сопоставлен"
    return f"{dot} <b>{_safe(home)} — {_safe(away)}</b> · {minute_txt}\n↳ {_safe(market)} · <b>{move}</b>{extra}"


def _send_market_tape(chat_id) -> None:
    if not _owner(chat_id):
        tg._send_reply(chat_id, "⛔ Линия LIVE доступна только владельцу.")
        return
    rows = tg._active_signal_rows()
    if not rows:
        tg._post_message(chat_id, "📈 <b>ЛИНИЯ LIVE</b>\n\nСейчас активных GOOL-сигналов нет.", _owner_keyboard())
        return
    lines = [
        f"📈 <b>ЛИНИЯ LIVE · {len(rows)}</b>",
        "<i>Самое сильное текущее движение рынка по активным GOOL-сигналам.</i>",
        "",
    ]
    for row in rows[:8]:
        lines.append(_market_line(row))
        lines.append("")
    if len(rows) > 8:
        lines.append(f"…ещё {len(rows)-8} активных матчей")
    lines.append("<i>Δ — изменение implied probability; данные идут с дополнительного market-node.</i>")
    tg._post_message(chat_id, "\n".join(lines), _owner_keyboard())
    logger.info("OWNER_MARKET_TAPE sent rows=%d", len(rows))


def _handle_message(message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text else ""
    if "@" in command:
        command = command.split("@", 1)[0]
    if command == "/market" or text.casefold() == _BUTTON.casefold():
        _send_market_tape(chat_id)
        return
    _orig_handle_message(message)
    # After /start or /menu, give only the owner the private augmented keyboard.
    if chat_id is not None and _owner(chat_id) and command in {"/start", "/menu"}:
        tg._post_message(chat_id, "👑 <i>Панель владельца</i>", _owner_keyboard())


tg._main_keyboard = _main_keyboard
tg._handle_message = _handle_message
tg.send_owner_market_tape = _send_market_tape
logger.info("Owner-only compact market tape enabled")
