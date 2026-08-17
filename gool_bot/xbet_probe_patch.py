"""Owner-only /xbetcheck command for read-only 1xBet LiveFeed testing."""
from __future__ import annotations

import logging

import telegram_subscribers as tg

logger = logging.getLogger("xbet_probe_patch")
_original_handle_message = tg._handle_message


def _handle_message(message: dict):
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text else ""
    if "@" in command:
        command = command.split("@", 1)[0]
    if command != "/xbetcheck":
        return _original_handle_message(message)

    chat_id = (message.get("chat") or {}).get("id")
    if chat_id is None:
        return
    if str(chat_id) != tg._owner_chat_id():
        tg._send_reply(chat_id, "⛔ 1xBet probe доступен только владельцу.")
        return

    tg._send_reply(chat_id, "🧪 Проверяю текущий GOOL LIVE через прямой 1xBet LiveFeed…")
    try:
        from live_engine import _feed
        from feed_live_discovery import parse_master_live
        from xbet_live_odds import probe_matches, format_probe

        body = _feed("f_1_0_0_en_1")
        matches = parse_master_live(body) if body else []
        result = probe_matches(matches)
        text_out = format_probe(result)
        # Telegram has a 4096-char text limit. The current test has only a few
        # matches, but split defensively if LIVE grows later.
        while text_out:
            part = text_out[:3900]
            cut = part.rfind("\n\n")
            if len(text_out) > 3900 and cut > 1000:
                part = text_out[:cut]
            tg._send_reply(chat_id, part)
            text_out = text_out[len(part):].lstrip()
        logger.info("1xBet owner probe completed: flash=%d xbet=%d", len(matches), result.get("xbet_live_count", 0))
    except Exception as exc:
        logger.exception("1xBet owner probe failed: %s", exc)
        tg._send_reply(chat_id, f"⚠️ 1xBet probe упал: <code>{type(exc).__name__}: {exc}</code>")


tg._handle_message = _handle_message
logger.info("1xBet /xbetcheck probe patch enabled")
