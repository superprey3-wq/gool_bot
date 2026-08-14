"""Lightweight GOOL LIVE heartbeat without extra match scans.

Wraps the existing LIVE scan only to collect operational counters. It does not
change evaluation, thresholds, signal selection or Telegram signal delivery.
"""
from __future__ import annotations

import logging
import os
import time
import requests

import live_candidate_patch as lc
import unified_bot
from telegram_subscribers import get_subscribers

logger = logging.getLogger("live_status_heartbeat")

STATUS_INTERVAL_SECONDS = max(300, int(os.getenv("GOOL_STATUS_INTERVAL_SECONDS", "600")))

STATUS = {
    "online": 0,
    "analyzed": 0,
    "tracked": 0,
    "last_scan": 0.0,
}

_orig_scan = unified_bot.scan_live_once


async def _scan_with_status():
    online = 0
    analyzed = 0

    orig_discover = unified_bot.discover_live_matches
    orig_parse = lc.parse_stats

    async def discover_counted(*args, **kwargs):
        nonlocal online
        matches = await orig_discover(*args, **kwargs)
        online = len(matches or [])
        return matches

    def parse_counted(*args, **kwargs):
        nonlocal analyzed
        parsed = orig_parse(*args, **kwargs)
        if parsed:
            analyzed += 1
        return parsed

    unified_bot.discover_live_matches = discover_counted
    lc.parse_stats = parse_counted
    try:
        result = await _orig_scan()
    finally:
        unified_bot.discover_live_matches = orig_discover
        lc.parse_stats = orig_parse
        state = unified_bot._load_sent()
        STATUS.update(
            online=online,
            analyzed=analyzed,
            tracked=sum(1 for key in state if str(key).startswith("TRACK:")),
            last_scan=time.time(),
        )
    return result


unified_bot.scan_live_once = _scan_with_status


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and ":" not in token:
        bot_id = os.getenv("TELEGRAM_BOT_ID", "").strip()
        if bot_id.isdigit():
            token = f"{bot_id}:{token}"
    return token


def heartbeat_text() -> str:
    age = int(max(0, time.time() - float(STATUS.get("last_scan", 0) or 0))) if STATUS.get("last_scan") else -1
    freshness = "только что" if 0 <= age < 90 else (f"{age // 60} мин назад" if age >= 0 else "ожидаю первый скан")
    return (
        "🟢 <b>GOOL AI работает</b>\n\n"
        f"⚽ Матчей онлайн: <b>{int(STATUS.get('online', 0))}</b>\n"
        f"👀 Анализирую: <b>{int(STATUS.get('analyzed', 0))}</b>\n"
        f"🎯 Сопровождаю сигналов: <b>{int(STATUS.get('tracked', 0))}</b>\n"
        f"🔄 Последний LIVE-скан: <b>{freshness}</b>"
    )


def send_heartbeat() -> bool:
    token = _token()
    if not token:
        return False
    recipients = get_subscribers()
    if not recipients:
        return False
    text = heartbeat_text()
    delivered = 0
    for chat_id in recipients:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": str(chat_id), "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=15,
            )
            if r.ok:
                delivered += 1
            else:
                logger.warning("Heartbeat Telegram failed HTTP %s for %s", r.status_code, chat_id)
        except requests.RequestException as exc:
            logger.warning("Heartbeat Telegram failed for %s: %s", chat_id, exc)
    logger.info("GOOL heartbeat delivered %d/%d", delivered, len(recipients))
    return delivered > 0
