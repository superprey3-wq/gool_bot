"""Visual Telegram wrapper with reliable text-first delivery and safe diagnostics."""
from __future__ import annotations

import asyncio
import logging
import os
import re

import requests

import feed_unified_bot  # noqa: F401 - installs full discovery/odds/history patches
import unified_bot
from signal_card import render_signal_card

logger = logging.getLogger("visual_feed_unified_bot")

_ORIGINAL_FORMAT = unified_bot._format_signal
_CARD_CONTEXT = None
_TOKEN_RE = re.compile(r"^\d{6,15}:[A-Za-z0-9_-]{20,}$")


def _format_signal(match, pressure, stats, recs, goal_times, reason="signal"):
    global _CARD_CONTEXT
    _CARD_CONTEXT = (match, pressure, recs)
    return _ORIGINAL_FORMAT(match, pressure, stats, recs, goal_times, reason)


def _telegram_credentials():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    # Optional split-token support for hosts where users prefer storing bot id
    # and secret separately. We NEVER infer bot id from chat id.
    if token and ":" not in token:
        bot_id = os.getenv("TELEGRAM_BOT_ID", "").strip()
        if bot_id.isdigit():
            token = f"{bot_id}:{token}"
    return token, chat_id


def telegram_config_status() -> tuple[bool, str]:
    token, chat_id = _telegram_credentials()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN is missing"
    if not _TOKEN_RE.match(token):
        return False, "TELEGRAM_BOT_TOKEN has invalid format (expected numeric_bot_id:secret)"
    if not chat_id:
        return False, "TELEGRAM_CHAT_ID is missing"
    return True, "ok"


def _send_text(text: str) -> bool:
    token, chat_id = _telegram_credentials()
    ok, reason = telegram_config_status()
    if not ok:
        logger.error("TELEGRAM CONFIG ERROR: %s", reason)
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        if not response.ok:
            description = ""
            try:
                payload = response.json()
                description = str(payload.get("description") or "")
            except ValueError:
                description = response.text[:300]
            if response.status_code == 404:
                logger.error("TELEGRAM AUTH ERROR: HTTP 404 Not Found. Bot token is invalid/revoked or incomplete. Token value is not logged.")
            elif response.status_code == 400:
                logger.error("TELEGRAM REQUEST ERROR: HTTP 400 %s (check TELEGRAM_CHAT_ID and message format)", description)
            elif response.status_code == 401:
                logger.error("TELEGRAM AUTH ERROR: HTTP 401 %s (bot token rejected)", description)
            elif response.status_code == 403:
                logger.error("TELEGRAM ACCESS ERROR: HTTP 403 %s (bot blocked/no access to target chat)", description)
            else:
                logger.error("TELEGRAM sendMessage failed: HTTP %s %s", response.status_code, description)
            return False
        logger.info("TELEGRAM text signal delivered")
        return True
    except requests.RequestException as exc:
        logger.error("TELEGRAM sendMessage exception: %s", exc)
        return False


def _send_photo(card_bytes: bytes) -> bool:
    token, chat_id = _telegram_credentials()
    ok, _ = telegram_config_status()
    if not ok or not card_bytes:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat_id},
            files={"photo": ("gool_live.png", card_bytes, "image/png")},
            timeout=20,
        )
        if not response.ok:
            logger.warning("Signal card upload failed: HTTP %s", response.status_code)
        return response.ok
    except requests.RequestException as exc:
        logger.warning("Signal card upload exception: %s", exc)
        return False


def telegram_send(text: str):
    global _CARD_CONTEXT
    context = _CARD_CONTEXT
    _CARD_CONTEXT = None
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
