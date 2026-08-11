"""Visual Telegram wrapper for the full feed_unified_bot stack.

The analytical pipeline stays untouched. For every Telegram LIVE message we try
to send a PNG card first; if rendering/upload fails, the original text signal is
still sent normally.
"""
from __future__ import annotations

import asyncio
import logging
import os

import requests

import feed_unified_bot  # noqa: F401 - installs full discovery/odds/history patches
import unified_bot
from signal_card import render_signal_card

logger = logging.getLogger("visual_feed_unified_bot")

_ORIGINAL_FORMAT = unified_bot._format_signal
_ORIGINAL_TELEGRAM_SEND = unified_bot.telegram_send
_CARD_CONTEXT = None


def _format_signal(match, pressure, stats, recs, goal_times, reason="signal"):
    global _CARD_CONTEXT
    _CARD_CONTEXT = (match, pressure, recs)
    return _ORIGINAL_FORMAT(match, pressure, stats, recs, goal_times, reason)


def _send_photo(card_bytes: bytes) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id or not card_bytes:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id},
            files={"photo": ("gool_live.png", card_bytes, "image/png")},
            timeout=20,
        )
        return response.ok
    except requests.RequestException:
        return False


def telegram_send(text: str):
    global _CARD_CONTEXT
    context = _CARD_CONTEXT
    _CARD_CONTEXT = None
    if context:
        match, pressure, recs = context
        try:
            card = render_signal_card(match, pressure, recs)
            if not _send_photo(card):
                logger.warning("Signal card upload failed for %s", getattr(match, "event_id", ""))
        except Exception as exc:
            logger.warning("Signal card rendering failed for %s: %s", getattr(match, "event_id", ""), exc)
    return _ORIGINAL_TELEGRAM_SEND(text)


unified_bot._format_signal = _format_signal
unified_bot.telegram_send = telegram_send


if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
