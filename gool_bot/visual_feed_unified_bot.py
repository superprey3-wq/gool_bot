"""Visual Telegram wrapper with reliable multi-user delivery and safe diagnostics."""
from __future__ import annotations

import asyncio
import logging
import os
import re

import requests

import feed_unified_bot  # noqa: F401 - installs full discovery/odds/history patches
import unified_bot
from signal_card import render_signal_card
from telegram_subscribers import get_subscribers, unsubscribe

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
    owner_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    # Optional split-token support for hosts where users prefer storing bot id
    # and secret separately. We NEVER infer bot id from chat id.
    if token and ":" not in token:
        bot_id = os.getenv("TELEGRAM_BOT_ID", "").strip()
        if bot_id.isdigit():
            token = f"{bot_id}:{token}"
    return token, owner_chat_id


def telegram_config_status() -> tuple[bool, str]:
    token, _ = _telegram_credentials()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN is missing"
    if not _TOKEN_RE.match(token):
        return False, "TELEGRAM_BOT_TOKEN has invalid format (expected numeric_bot_id:secret)"
    if not get_subscribers():
        return False, "No Telegram subscribers yet; send /start to the bot"
    return True, "ok"


def _response_description(response: requests.Response) -> str:
    try:
        payload = response.json()
        return str(payload.get("description") or "")
    except ValueError:
        return response.text[:300]


def _send_text_to_chat(token: str, chat_id: str, text: str) -> bool:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if response.ok:
            return True
        description = _response_description(response)
        if response.status_code == 403:
            logger.warning("Telegram chat %s unavailable/blocked; subscriber removed", chat_id)
            unsubscribe(chat_id)
        elif response.status_code == 404:
            logger.error("TELEGRAM AUTH ERROR: HTTP 404 Not Found. Bot token is invalid/revoked or incomplete.")
        elif response.status_code == 401:
            logger.error("TELEGRAM AUTH ERROR: HTTP 401 %s", description)
        else:
            logger.warning("Telegram sendMessage to %s failed: HTTP %s %s", chat_id, response.status_code, description)
    except requests.RequestException as exc:
        logger.warning("Telegram sendMessage to %s failed: %s", chat_id, exc)
    return False


def _send_text(text: str) -> bool:
    token, _ = _telegram_credentials()
    if not token or not _TOKEN_RE.match(token):
        logger.error("TELEGRAM CONFIG ERROR: invalid or missing bot token")
        return False

    recipients = get_subscribers()
    if not recipients:
        logger.warning("Telegram signal skipped: no subscribers")
        return False

    delivered = 0
    for chat_id in recipients:
        if _send_text_to_chat(token, chat_id, text):
            delivered += 1
    logger.info("TELEGRAM text signal delivered to %d/%d subscribers", delivered, len(recipients))
    return delivered > 0


def _send_photo(card_bytes: bytes) -> bool:
    token, _ = _telegram_credentials()
    if not token or not _TOKEN_RE.match(token) or not card_bytes:
        return False

    recipients = get_subscribers()
    delivered = 0
    for chat_id in recipients:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id},
                files={"photo": ("gool_live.png", card_bytes, "image/png")},
                timeout=20,
            )
            if response.ok:
                delivered += 1
            elif response.status_code == 403:
                logger.warning("Telegram chat %s unavailable/blocked during photo send", chat_id)
                unsubscribe(chat_id)
            else:
                logger.warning(
                    "Signal card upload to %s failed: HTTP %s %s",
                    chat_id,
                    response.status_code,
                    _response_description(response),
                )
        except requests.RequestException as exc:
            logger.warning("Signal card upload to %s failed: %s", chat_id, exc)
    return delivered > 0


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
                logger.warning(
                    "Signal card upload failed for %s; text signal was delivered",
                    getattr(match, "event_id", ""),
                )
        except Exception as exc:
            logger.warning(
                "Signal card rendering failed for %s: %s; text signal was delivered",
                getattr(match, "event_id", ""),
                exc,
            )
    return True


unified_bot._format_signal = _format_signal
unified_bot.telegram_send = telegram_send


if __name__ == "__main__":
    asyncio.run(unified_bot.scan_live_once())
