"""Visual Telegram wrapper with reliable text-first delivery.

Text is the signal of record. A PNG card is best-effort only and can never block
or hide a valid LIVE signal.
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
_CARD_CONTEXT = None


def _format_signal(match, pressure, stats, recs, goal_times, reason="signal"):
    global _CARD_CONTEXT
    _CARD_CONTEXT = (match, pressure, recs)
    return _ORIGINAL_FORMAT(match, pressure, stats, recs, goal_times, reason)


def _telegram_credentials():
    # Read env at SEND time. This avoids stale empty values captured when
    # unified_bot was imported before the hosting environment was fully ready.
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _send_text(text: str) -> bool:
    token, chat_id = _telegram_credentials()
    if not token or not chat_id:
        logger.error("TELEGRAM SEND blocked: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        if not response.ok:
            logger.error("TELEGRAM sendMessage failed: HTTP %s %s", response.status_code, response.text[:500])
            return False
        logger.info("TELEGRAM text signal delivered")
        return True
    except requests.RequestException as exc:
        logger.error("TELEGRAM sendMessage exception: %s", exc)
        return False


def _send_photo(card_bytes: bytes) -> bool:
    token, chat_id = _telegram_credentials()
    if not token or not chat_id or not card_bytes:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id},
            files={"photo": ("gool_live.png", card_bytes, "image/png")},
            timeout=20,
        )
        if not response.ok:
            logger.warning("Signal card upload failed: HTTP %s %s", response.status_code, response.text[:300])
        return response.ok
    except requests.RequestException as exc:
        logger.warning("Signal card upload exception: %s", exc)
        return False


def telegram_send(text: str):
    global _CARD_CONTEXT
    context = _CARD_CONTEXT
    _CARD_CONTEXT = None

    # IMPORTANT: deliver text first. Card rendering/upload is optional and must
    # never prevent the actual betting signal from reaching Telegram.
    delivered = _send_text(text)
    if not delivered:
        return False

    if context:
        match, pressure, recs = context
        try:
            card = render_signal_card(match, pressure, recs)
            if not _send_photo(card):
                logger.warning("Signal card upload failed for %s; text signal was delivered", getattr(match, "event_id", ""))
        except Exception as exc:
            logger.warning("Signal card rendering failed for %s: %s; text signal was delivered", getattr(match, "event_id", ""), exc)
    return True


unified_bot._format_signal = _format_signal
unified_bot.telegram_send = telegram_send


if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
