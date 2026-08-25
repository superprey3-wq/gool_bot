"""Telegram subscribers, commands and robust in-game view for GOOL production."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger("telegram_subscribers")
MOSCOW = ZoneInfo("Europe/Moscow")
BUILD_ID = "GOOL-PROD-LIVEFIX-3"
LEGACY_SUBSCRIBERS_FILE = Path(__file__).with_name("telegram_subscribers.json")
_PENDING = {"", "pending", "wait", "waiting"}


def _default_subscribers_file() -> Path:
    explicit = os.getenv("TELEGRAM_SUBSCRIBERS_FILE", "").strip()
    if explicit:
        return Path(explicit)
    runtime = os.getenv("RUNTIME_DATA_DIR", "").strip()
    if runtime:
        return Path(runtime) / "telegram_subscribers.json"
    data = Path("/data")
    if data.exists() and os.access(str(data), os.W_OK):
        return data / "telegram_subscribers.json"
    db = os.getenv("DATABASE_PATH", "").strip()
    if db:
        p = Path(db)
        if p.is_absolute():
            return p.parent / "telegram_subscribers.json"
    return LEGACY_SUBSCRIBERS_FILE


SUBSCRIBERS_FILE = _default_subscribers_file()


def _token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token and ":" not in token:
        bot_id = os.getenv("TELEGRAM_BOT_ID", "").strip()
        if bot_id.isdigit():
            token = f"{bot_id}:{token}"
    return token


def _owner_chat_id() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


def _extra_chat_ids() -> set[str]:
    raw = os.getenv("TELEGRAM_EXTRA_CHAT_IDS", "")
    return {x for x in re.split(r"[\s,;]+", raw.strip()) if x}


def _read_file(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return set()
        return {str(x).strip() for x in data if str(x).strip()}
    except Exception as exc:
        logger.warning("Could not read Telegram subscribers from %s: %s", path, exc)
        return set()


def _write_saved(chat_ids: Iterable[str]) -> None:
    values = sorted({str(x).strip() for x in chat_ids if str(x).strip()})
    try:
        SUBSCRIBERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SUBSCRIBERS_FILE.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Could not save Telegram subscribers to %s: %s", SUBSCRIBERS_FILE, exc)


def _read_saved() -> set[str]:
    saved = _read_file(SUBSCRIBERS_FILE)
    if SUBSCRIBERS_FILE != LEGACY_SUBSCRIBERS_FILE:
        legacy = _read_file(LEGACY_SUBSCRIBERS_FILE)
        if legacy - saved:
            saved |= legacy
            _write_saved(saved)
            logger.info("Migrated %d Telegram subscriber(s) from legacy storage", len(legacy))
    return saved


def get_subscribers() -> list[str]:
    subscribers = _read_saved() | _extra_chat_ids()
    owner = _owner_chat_id()
    if owner:
        subscribers.add(owner)
    return sorted(subscribers)


def subscribe(chat_id) -> bool:
    chat_id = str(chat_id).strip()
    if not chat_id:
        return False
    saved = _read_saved()
    before = len(saved)
    saved.add(chat_id)
    _write_saved(saved)
    return len(saved) != before


def unsubscribe(chat_id) -> bool:
    chat_id = str(chat_id).strip()
    saved = _read_saved()
    existed = chat_id in saved
    saved.discard(chat_id)
    _write_saved(saved)
    return existed


def _main_keyboard():
    return {
        "keyboard": [
            [{"text": "🟢 В игре"}, {"text": "📊 Отчёт"}],
            [{"text": "🧠 Анализ"}],
        ],
        "resize_keyboard": True,
    }


def _post_message(chat_id, text: str, reply_markup=None) -> bool:
    token = _token()
    if not token:
        return False
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=15,
        )
        if response.ok:
            return True
        logger.warning("Telegram reply failed: HTTP %s %s", response.status_code, response.text[:300])
    except requests.RequestException as exc:
        logger.warning("Telegram reply failed: %s", exc)
    return False


def _send_reply(chat_id, text: str, keyboard: bool = True) -> bool:
    if keyboard and _post_message(chat_id, text, _main_keyboard()):
        return True
    return _post_message(chat_id, text)


def _send_journal(chat_id) -> None:
    if str(chat_id) != _owner_chat_id():
        _send_reply(chat_id, "⛔ Экспорт журнала доступен только владельцу.")
        return
    journal = Path(os.getenv("SIGNAL_JOURNAL_FILE", "signal_journal.json"))
    if not journal.is_absolute():
        journal = Path.cwd() / journal
    if not journal.exists():
        _send_reply(chat_id, f"⚠️ Журнал не найден: <code>{journal}</code>")
        return
    token = _token()
    try:
        with journal.open("rb") as fh:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": str(chat_id), "caption": "📦 GOOL · signal_journal.json"},
                files={"document": ("signal_journal.json", fh, "application/json")},
                timeout=60,
            )
        if response.ok:
            return
        logger.warning("Telegram journal export failed: HTTP %s %s", response.status_code, response.text[:300])
    except (OSError, requests.RequestException) as exc:
        logger.exception("Telegram journal export failed: %s", exc)
    _send_reply(chat_id, "⚠️ Не удалось отправить журнал. Ошибка записана в лог.")


def _row_pending(row: dict) -> bool:
    signal_result = str(row.get("signal_result") or "").strip().lower()
    if signal_result and signal_result not in _PENDING:
        return False
    return str(row.get("result") or "pending").strip().lower() in _PENDING


def _active_signal_rows() -> list[dict]:
    """Read active GOOL signals directly from the journal.

    This intentionally does not import report_now or require a live Flashscore lookup,
    so Telegram /live cannot break when reporting internals change.
    """
    try:
        from signal_journal import all_signals
        from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15
    except Exception as exc:
        logger.exception("IN_GAME imports failed: %s", exc)
        return []

    now = time.time()
    latest: dict[str, dict] = {}
    try:
        rows = all_signals()
    except Exception as exc:
        logger.exception("IN_GAME journal read failed: %s", exc)
        return []

    for row in rows:
        if not isinstance(row, dict) or row.get("kind") != "live" or not _row_pending(row):
            continue
        event_id = str(row.get("event_id") or "")
        if not event_id:
            continue
        try:
            created = float(row.get("created_ts", 0) or 0)
        except (TypeError, ValueError):
            created = 0.0
        if created and now - created > 6 * 3600:
            continue

        engine = str(row.get("engine") or "core")
        reason = str(row.get("reason") or "signal")
        is_aux = engine in {FIRST_HALF_GOAL, SECOND_HALF_OVER15}
        is_core = not is_aux and reason in {"signal", "reentry"}
        if not (is_core or is_aux):
            continue

        key = f"{engine}:{event_id}"
        old = latest.get(key)
        if old is None or created >= float(old.get("created_ts", 0) or 0):
            latest[key] = row

    return sorted(latest.values(), key=lambda r: float(r.get("created_ts", 0) or 0), reverse=True)


def _engine_label(row: dict) -> str:
    engine = str(row.get("engine") or "core")
    if engine == "first_half_goal":
        return "1T · ГОЛ"
    if engine == "second_half_over15":
        return "2T · 2+ ГОЛА"
    return "CORE · ГОЛ"


def _live_text(rows: list[dict]) -> str:
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
        lines.append(f"\n…и ещё {len(rows) - 20}")
    return "\n".join(lines)


def _send_live(chat_id) -> None:
    try:
        rows = _active_signal_rows()
        if not _send_reply(chat_id, _live_text(rows), keyboard=True):
            logger.warning("IN_GAME delivery failed for %s", chat_id)
        else:
            logger.info("IN_GAME sent to %s rows=%d build=%s", chat_id, len(rows), BUILD_ID)
    except Exception as exc:
        logger.exception("IN_GAME handler failed: %s", exc)
        _send_reply(chat_id, "⚠️ Не удалось обновить список. Попробуй ещё раз через несколько секунд.")


def _send_report(chat_id) -> None:
    _send_reply(chat_id, "📊 Собираю текущий отчёт…")
    try:
        from report_now import build_report_text
        _send_reply(chat_id, build_report_text())
    except Exception as exc:
        logger.exception("Telegram /report failed: %s", exc)
        _send_reply(chat_id, "⚠️ Не удалось собрать отчёт прямо сейчас. Ошибка записана в лог.")


def _handle_message(message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text else ""
    if "@" in command:
        command = command.split("@", 1)[0]

    if command != "/stop":
        subscribe(chat_id)

    if command in {"/start", "/menu"}:
        name = str((message.get("from") or {}).get("first_name") or "").strip()
        greeting = f", {name}" if name else ""
        _send_reply(
            chat_id,
            "✅ <b>GOOL AI подключён</b>" + greeting + "!\n\n"
            "LIVE-сигналы будут приходить сюда.\n\n"
            "/status — подписка и версия\n/live — активные сигналы\n"
            "/report — отчёт\n/analysis — анализ\n/stop — отключить рассылку",
        )
    elif command == "/stop":
        if str(chat_id) == _owner_chat_id():
            _send_reply(chat_id, "👑 Основной чат владельца всегда остаётся активным.")
            return
        unsubscribe(chat_id)
        _send_reply(chat_id, "🔕 Рассылка GOOL AI отключена. Вернуть её можно командой /start.")
    elif command in {"/status", "/version"}:
        active = str(chat_id) in set(get_subscribers())
        status = "✅ активна" if active else "🔕 отключена"
        _send_reply(
            chat_id,
            f"🤖 <b>{BUILD_ID}</b>\nПодписка: {status}\nПолучателей: <b>{len(get_subscribers())}</b>",
        )
    elif command == "/journal":
        _send_journal(chat_id)
    elif command == "/live" or text.casefold() in {"🟢 в игре", "в игре"}:
        _send_live(chat_id)
    elif command == "/report" or text.casefold() == "📊 отчёт":
        _send_report(chat_id)
    elif command == "/analysis" or text.casefold() == "🧠 анализ":
        _send_reply(chat_id, "🧠 Анализирую сегодняшние закрытые сигналы…")
        try:
            from signal_analysis import build_analysis_text
            _send_reply(chat_id, build_analysis_text())
        except Exception as exc:
            logger.exception("Telegram /analysis failed: %s", exc)
            _send_reply(chat_id, "⚠️ Не удалось выполнить анализ. Ошибка записана в лог.")


def _answer_callback(callback_id, text: str = "") -> None:
    token = _token()
    if not token:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": str(callback_id), "text": text},
            timeout=10,
        )
    except requests.RequestException:
        pass


def _handle_callback(query: dict) -> None:
    callback_id = query.get("id")
    data = str(query.get("data") or "")
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not callback_id or chat_id is None or not data.startswith("show:"):
        return
    subscribe(chat_id)
    event_id = data.split(":", 1)[1]
    try:
        from signal_card_archive import get_entry_card
        card = get_entry_card(event_id)
    except Exception as exc:
        logger.warning("Archived card lookup failed: %s", exc)
        card = None
    if not card:
        _answer_callback(callback_id, "Карточка недоступна")
        _send_reply(chat_id, "ℹ️ Карточка этого старого сигнала недоступна.")
        return
    token = _token()
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            json={
                "chat_id": str(chat_id),
                "photo": card.get("file_id"),
                "caption": card.get("caption") or "🎯 GOOL AI • АНАЛИТИЧЕСКИЙ СИГНАЛ",
            },
            timeout=20,
        )
        _answer_callback(callback_id, "Открываю сигнал" if response.ok else "Не удалось открыть карточку")
    except requests.RequestException:
        _answer_callback(callback_id, "Ошибка Telegram")


def _poll_once(offset):
    token = _token()
    if not token:
        return offset
    params = {"timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])}
    if offset is not None:
        params["offset"] = offset
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params=params,
            timeout=35,
        )
        if not response.ok:
            logger.warning("Telegram getUpdates failed: HTTP %s %s", response.status_code, response.text[:200])
            return offset
        for update in response.json().get("result") or []:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            try:
                if isinstance(update.get("message"), dict):
                    _handle_message(update["message"])
                elif isinstance(update.get("callback_query"), dict):
                    _handle_callback(update["callback_query"])
            except Exception as exc:
                logger.exception("Telegram update handler failed but polling continues: %s", exc)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Telegram polling failed: %s", exc)
    except Exception as exc:
        logger.exception("Unexpected Telegram polling error: %s", exc)
    return offset


async def polling_loop():
    offset = None
    logger.info(
        "Telegram polling started | build=%s subscribers=%d storage=%s",
        BUILD_ID,
        len(get_subscribers()),
        SUBSCRIBERS_FILE,
    )
    while True:
        try:
            offset = await asyncio.to_thread(_poll_once, offset)
        except Exception as exc:
            logger.exception("Telegram polling iteration crashed; restarting: %s", exc)
        await asyncio.sleep(0.5)
