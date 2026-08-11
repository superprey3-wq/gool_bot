"""Unified PREMATCH + LIVE bot runner."""
from __future__ import annotations

import asyncio
import logging
import os
import time
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

_sent: dict[str, float] = {}


def telegram_send(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("Telegram secrets missing")
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
    reasons = "\n".join(f"• {x}" for x in pressure.reasons[:4]) or "• устойчивое давление"
    odds_line = "💰 Коэффициент: нет данных"
    if odds_info:
        odds_line = f"💰 {odds_info[0]}: <b>{odds_info[1]:.2f}</b>"
    return (
        f"🔴 <b>LIVE GOAL SIGNAL</b>\n\n"
        f"⚽ <b>{match.home} — {match.away}</b>\n"
        f"⏱ {match.minute}' | {match.home_score}:{match.away_score}\n\n"
        f"xG: <b>{pair('xg')}</b>\n"
        f"Удары: {pair('shots')}\n"
        f"В створ: {pair('shots_on_target')}\n"
        f"Big chances: {pair('big_chances')}\n"
        f"Удары из штрафной: {pair('shots_inside_box')}\n"
        f"Угловые: {pair('corners')}\n\n"
        f"⚡ Momentum: <b>{pressure.momentum:.0f}/100</b>\n"
        f"🔥 Goal Pressure: <b>{pressure.score:.0f}/100</b>\n"
        f"{odds_line}\n\n"
        f"Почему сигнал:\n{reasons}"
    )


async def scan_live_once() -> int:
    live = await discover_live_matches()
    logger.info("LIVE matches found: %d", len(live))
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
        if pressure.score < LIVE_SIGNAL_THRESHOLD:
            continue
        now = time.time()
        if now - _sent.get(match.event_id, 0) < LIVE_COOLDOWN_MINUTES * 60:
            continue
        odds_entries = _fetch_event_odds(match.event_id)
        odds_info = _best_live_total(odds_entries, match.home_score + match.away_score)
        if telegram_send(_format_signal(match, pressure, stats, odds_info)):
            _sent[match.event_id] = now
            sent += 1
    logger.info("LIVE signals sent: %d", sent)
    return sent


async def main() -> None:
    logger.info("Unified GOOL BOT started; live interval=%ss threshold=%.0f", LIVE_SCAN_SECONDS, LIVE_SIGNAL_THRESHOLD)
    while True:
        try:
            await scan_live_once()
        except Exception as exc:
            logger.exception("Live cycle failed: %s", exc)
        await asyncio.sleep(LIVE_SCAN_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
