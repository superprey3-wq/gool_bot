"""Unified PREMATCH + LIVE bot runner."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

from live_engine import (
    StatsSnapshot,
    calculate_goal_pressure,
    discover_live_matches,
    fetch_stats,
    get_previous_values,
    parse_stats,
    save_snapshot,
)
from prematch_scanner import _fetch_event_odds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("unified_bot")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
LIVE_SCAN_SECONDS = int(os.getenv("LIVE_SCAN_SECONDS", "60"))
LIVE_SIGNAL_THRESHOLD = float(os.getenv("LIVE_SIGNAL_THRESHOLD", "75"))
LIVE_COOLDOWN_MINUTES = int(os.getenv("LIVE_COOLDOWN_MINUTES", "12"))
SENT_STATE_FILE = Path(os.getenv("LIVE_SENT_STATE_FILE", "live_sent.json"))


def _load_sent() -> dict[str, float]:
    if not SENT_STATE_FILE.exists():
        return {}
    try:
        data = json.loads(SENT_STATE_FILE.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()}
    except Exception:
        return {}


def _save_sent(data: dict[str, float]) -> None:
    cutoff = time.time() - 6 * 3600
    clean = {k: v for k, v in data.items() if v >= cutoff}
    SENT_STATE_FILE.write_text(json.dumps(clean, ensure_ascii=False), encoding="utf-8")


def telegram_send(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Секреты Telegram не настроены")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        return r.ok
    except requests.RequestException:
        return False


def _best_live_total(entries: list[dict[str, Any]], total_goals: int) -> tuple[str, float] | None:
    candidates: list[tuple[float, str, float]] = []
    for entry in entries:
        if str(entry.get("bettingType")) != "OVER_UNDER":
            continue
        if str(entry.get("bettingScope") or "FULL_TIME") != "FULL_TIME":
            continue
        for item in entry.get("odds") or []:
            if not isinstance(item, dict) or not item.get("active", True):
                continue
            if str(item.get("selection") or "").upper() != "OVER":
                continue
            handicap = item.get("handicap") or {}
            try:
                line = float(handicap.get("value"))
                value = float(item.get("value"))
            except (TypeError, ValueError):
                continue
            if line <= total_goals:
                continue
            distance = line - (total_goals + 0.5)
            candidates.append((abs(distance), f"ТБ {line:g}", value))
    if not candidates:
        return None
    _, label, value = min(candidates, key=lambda x: x[0])
    return label, value


def _format_signal(match, pressure, stats, odds_info) -> str:
    def pair(key: str) -> str:
        a, b = stats.get(key, (0, 0))
        return f"{a:g} — {b:g}"

    reasons = "\n".join(f"• {x}" for x in pressure.reasons[:4]) or "• устойчивое давление на ворота"
    odds_line = "💰 Текущий коэффициент: нет данных"
    if odds_info:
        odds_line = f"💰 {odds_info[0]}: <b>{odds_info[1]:.2f}</b>"

    if pressure.score >= 90:
        level = "🔥 ОЧЕНЬ СИЛЬНОЕ"
    elif pressure.score >= 82:
        level = "🔥 СИЛЬНОЕ"
    else:
        level = "⚡ ПОВЫШЕННОЕ"

    return (
        f"🔴 <b>LIVE-СИГНАЛ НА ГОЛ</b>\n\n"
        f"⚽ <b>{match.home} — {match.away}</b>\n"
        f"⏱ {match.minute}' | Счёт {match.home_score}:{match.away_score}\n\n"
        f"📊 <b>Статистика в матче</b>\n"
        f"Ожидаемые голы (xG): <b>{pair('xg')}</b>\n"
        f"Удары: {pair('shots')}\n"
        f"Удары в створ: {pair('shots_on_target')}\n"
        f"Большие голевые моменты: {pair('big_chances')}\n"
        f"Удары из штрафной: {pair('shots_inside_box')}\n"
        f"Касания в штрафной: {pair('touches_box')}\n"
        f"Угловые: {pair('corners')}\n\n"
        f"⚡ Динамика давления: <b>{pressure.momentum:.0f}/100</b>\n"
        f"🔥 Давление на гол: <b>{pressure.score:.0f}/100</b>\n"
        f"📈 Оценка ситуации: <b>{level}</b>\n"
        f"{odds_line}\n\n"
        f"🎯 <b>Возможен ещё один гол</b>\n\n"
        f"Почему появился сигнал:\n{reasons}"
    )


async def scan_live_once() -> int:
    live = await discover_live_matches()
    logger.info("Найдено LIVE-матчей: %d", len(live))
    sent_state = _load_sent()
    sent = 0

    for match in live:
        body = fetch_stats(match.event_id)
        if not body:
            continue
        stats = parse_stats(body)
        if not stats:
            continue

        previous = get_previous_values(match.event_id, match.minute, 8)
        pressure = calculate_goal_pressure(match, stats, previous)
        save_snapshot(match.event_id, StatsSnapshot(int(time.time()), match.minute, stats))

        logger.info(
            "%s - %s %d' pressure=%.1f momentum=%.1f",
            match.home, match.away, match.minute, pressure.score, pressure.momentum,
        )

        if pressure.score < LIVE_SIGNAL_THRESHOLD:
            continue

        now = time.time()
        if now - sent_state.get(match.event_id, 0) < LIVE_COOLDOWN_MINUTES * 60:
            continue

        odds_entries = _fetch_event_odds(match.event_id)
        odds_info = _best_live_total(odds_entries, match.home_score + match.away_score)
        if telegram_send(_format_signal(match, pressure, stats, odds_info)):
            sent_state[match.event_id] = now
            _save_sent(sent_state)
            sent += 1

    logger.info("Отправлено LIVE-сигналов: %d", sent)
    return sent


async def main() -> None:
    logger.info("GOOL BOT запущен; интервал LIVE=%s сек, порог=%.0f", LIVE_SCAN_SECONDS, LIVE_SIGNAL_THRESHOLD)
    while True:
        try:
            await scan_live_once()
        except Exception as exc:
            logger.exception("Ошибка LIVE-цикла: %s", exc)
        await asyncio.sleep(LIVE_SCAN_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
