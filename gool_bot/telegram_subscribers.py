"""Telegram subscriber registry and /start command polling."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Iterable

import requests

logger = logging.getLogger("telegram_subscribers")

SUBSCRIBERS_FILE = Path(
    os.getenv(
        "TELEGRAM_SUBSCRIBERS_FILE",
        str(Path(__file__).with_name("telegram_subscribers.json")),
    )
)


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and ":" not in token:
        bot_id = os.getenv("TELEGRAM_BOT_ID", "").strip()
        if bot_id.isdigit():
            token = f"{bot_id}:{token}"
    return token


def _owner_chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _read_saved() -> set[str]:
    if not SUBSCRIBERS_FILE.exists():
        return set()
    try:
        data = json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(item).strip() for item in data if str(item).strip()}
    except Exception as exc:
        logger.warning("Could not read Telegram subscribers: %s", exc)
    return set()


def _write_saved(chat_ids: Iterable[str]) -> None:
    values = sorted({str(chat_id).strip() for chat_id in chat_ids if str(chat_id).strip()})
    try:
        SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUBSCRIBERS_FILE.write_text(
            json.dumps(values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Could not save Telegram subscribers: %s", exc)


def get_subscribers() -> list[str]:
    subscribers = _read_saved()
    owner = _owner_chat_id()
    if owner:
        subscribers.add(owner)
    return sorted(subscribers)


def subscribe(chat_id: str | int) -> bool:
    chat_id = str(chat_id).strip()
    if not chat_id:
        return False
    subscribers = _read_saved()
    before = len(subscribers)
    subscribers.add(chat_id)
    _write_saved(subscribers)
    return len(subscribers) != before


def unsubscribe(chat_id: str | int) -> bool:
    chat_id = str(chat_id).strip()
    subscribers = _read_saved()
    existed = chat_id in subscribers
    subscribers.discard(chat_id)
    _write_saved(subscribers)
    return existed


def _send_reply(chat_id: str | int, text: str) -> None:
    token = _token()
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": str(chat_id),
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.warning("Telegram command reply failed: %s", exc)


def _handle_message(message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return

    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].lower()
    if "@" in command:
        command = command.split("@", 1)[0]

    if command == "/start":
        subscribe(chat_id)
        name = str((message.get("from") or {}).get("first_name") or "").strip()
        greeting = f", {name}" if name else ""
        _send_reply(
            chat_id,
            "✅ <b>GOOL AI подключён</b>" + greeting + "!\n\n"
            "Теперь сюда будут приходить PREMATCH и LIVE-сигналы бота.\n"
            "Чтобы отключить рассылку, отправь /stop.\n"
            "Проверить подписку: /status\n"
            "Текущий итог за день: /report",
        )
        logger.info("Telegram subscriber activated: %s", chat_id)
    elif command == "/stop":
        owner = _owner_chat_id()
        if str(chat_id) == owner:
            _send_reply(chat_id, "👑 Основной чат владельца всегда остаётся активным.")
            return
        unsubscribe(chat_id)
        _send_reply(chat_id, "🔕 Рассылка GOOL AI отключена. Вернуть её можно командой /start.")
        logger.info("Telegram subscriber deactivated: %s", chat_id)
    elif command == "/status":
        active = str(chat_id) in set(get_subscribers())
        text = "✅ Подписка активна." if active else "🔕 Подписка отключена. Отправь /start."
        _send_reply(chat_id, text)
    elif command == "/report":
        try:
            from report_now import build_report_text
            _send_reply(chat_id, build_report_text())
            logger.info("Telegram report sent to: %s", chat_id)
        except Exception as exc:
            logger.exception("Telegram /report failed: %s", exc)
            _send_reply(chat_id, "⚠️ Не удалось собрать отчёт прямо сейчас. Попробуй ещё раз через минуту.")


def _poll_once(offset: int | None) -> int | None:
    token = _token()
    if not token:
        return offset
    params = {"timeout": 25, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params=params,
            timeout=35,
        )
        if not response.ok:
            logger.warning("Telegram getUpdates failed: HTTP %s", response.status_code)
            return offset
        payload = response.json()
        updates = payload.get("result") or []
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            message = update.get("message")
            if isinstance(message, dict):
                _handle_message(message)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Telegram polling failed: %s", exc)
    return offset


async def polling_loop() -> None:
    """Continuously process Telegram bot commands without blocking LIVE scans."""
    offset: int | None = None
    logger.info("Telegram command polling started")
    while True:
        offset = await asyncio.to_thread(_poll_once, offset)
        await asyncio.sleep(0.5)
