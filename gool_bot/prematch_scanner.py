"""Prematch totals movement scanner.

Uses OddsHarvester for bookmaker odds history. The job is intentionally
short-lived so it can run from GitHub Actions every five minutes without a
persistent server.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prematch_scanner")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MIN_MINUTES_TO_KICKOFF = int(os.getenv("MIN_MINUTES_TO_KICKOFF", "2"))
MAX_MINUTES_TO_KICKOFF = int(os.getenv("MAX_MINUTES_TO_KICKOFF", "9"))
MIN_BOOKMAKERS = int(os.getenv("MIN_BOOKMAKERS", "3"))
MIN_CONSENSUS = float(os.getenv("MIN_CONSENSUS", "0.65"))
MIN_MEDIAN_DROP = float(os.getenv("MIN_MEDIAN_DROP", "8.0"))
MAX_SIGNALS_PER_MATCH = int(os.getenv("MAX_SIGNALS_PER_MATCH", "4"))

# OddsHarvester officially supports regional OddsPortal mirrors through
# --base-url. GitHub-hosted IPs currently receive an empty event grid from the
# default www.oddsportal.com domain, so use the regional mirror explicitly.
ODDSPORTAL_BASE_URL = os.getenv("ODDSPORTAL_BASE_URL", "https://www.centroquote.it")

PERIODS = {
    "full_time": "Матч",
    "1st_half": "1-й тайм",
    "2nd_half": "2-й тайм",
}


@dataclass
class MovementSignal:
    period: str
    line: str
    side: str
    median_open: float
    median_current: float
    median_drop: float
    consensus: float
    bookmakers: int
    score: float


def _run_oddsharvester(args: list[str], output_path: Path) -> Any:
    cmd = [
        "oddsharvester",
        *args,
        "--base-url", ODDSPORTAL_BASE_URL,
        "-f", "json",
        "-o", str(output_path),
        "--headless",
    ]
    logger.info("OddsHarvester base=%s command=%s", ODDSPORTAL_BASE_URL, " ".join(args[:8]))
    subprocess.run(cmd, check=True, timeout=240)
    if not output_path.exists():
        return []
    return json.loads(output_path.read_text(encoding="utf-8"))


def _walk_records(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if any(k in node for k in ("home_team", "away_team", "match_link", "kickoff_utc", "match_date")):
            found.append(node)
        for value in node.values():
            found.extend(_walk_records(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_walk_records(value))
    return found


def _parse_kickoff(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace(" UTC", "+00:00").replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


def _collect_upcoming_links() -> list[dict[str, Any]]:
    """Collect a broad one-hour grid, then apply our precise 2-9 minute window."""
    now = datetime.now(UTC)
    dates = {now.date(), (now + timedelta(hours=12)).date()}
    matches: dict[str, dict[str, Any]] = {}

    with tempfile.TemporaryDirectory() as tmp:
        for day in sorted(dates):
            date = day.strftime("%Y%m%d")
            out = Path(tmp) / f"links-{date}.json"
            try:
                payload = _run_oddsharvester(
                    [
                        "upcoming", "-s", "football", "-d", date,
                        "--links-only",
                        # Wide collection window makes this resilient to cron drift;
                        # precise filtering is done below using kickoff_utc.
                        "--kickoff-within-hours", "1",
                        "--timezone", "UTC",
                    ],
                    out,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                logger.warning("Upcoming collection failed for %s: %s", date, exc)
                continue

            for row in _walk_records(payload):
                link = row.get("match_link") or row.get("match_url")
                kickoff = _parse_kickoff(row.get("kickoff_utc") or row.get("match_date"))
                if not link or not kickoff:
                    continue
                minutes = (kickoff - now).total_seconds() / 60
                if MIN_MINUTES_TO_KICKOFF <= minutes <= MAX_MINUTES_TO_KICKOFF:
                    row["_kickoff_dt"] = kickoff
                    matches[str(link)] = row

    logger.info("Matches in final %d-%d minute window: %d", MIN_MINUTES_TO_KICKOFF, MAX_MINUTES_TO_KICKOFF, len(matches))
    return list(matches.values())


def _bookmaker_entries(node: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("bookmaker_name") and node.get("odds_history_data"):
            result.append(node)
        for value in node.values():
            result.extend(_bookmaker_entries(value))
    elif isinstance(node, list):
        for value in node:
            result.extend(_bookmaker_entries(value))
    return result


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opening(history_item: Any) -> float | None:
    if not isinstance(history_item, dict):
        return None
    opening = history_item.get("opening_odds")
    return _number(opening.get("odds")) if isinstance(opening, dict) else None


def _movement_signals(payload: Any, period_label: str) -> list[MovementSignal]:
    buckets: dict[tuple[str, str], list[tuple[float, float]]] = {}

    for entry in _bookmaker_entries(payload):
        histories = entry.get("odds_history_data") or []
        if not isinstance(histories, list):
            continue
        line = str(entry.get("submarket_name") or entry.get("market") or "Over/Under")

        for index, (side, current_key) in enumerate((("ТБ", "odds_over"), ("ТМ", "odds_under"))):
            current = _number(entry.get(current_key))
            opening = _opening(histories[index]) if index < len(histories) else None
            if opening is None or current is None or opening <= 1 or current <= 1:
                continue
            buckets.setdefault((line, side), []).append((opening, current))

    signals: list[MovementSignal] = []
    for (line, side), pairs in buckets.items():
        if len(pairs) < MIN_BOOKMAKERS:
            continue
        drops = [((opening - current) / opening) * 100 for opening, current in pairs]
        consensus = sum(drop > 0 for drop in drops) / len(drops)
        median_drop = statistics.median(drops)
        if median_drop < MIN_MEDIAN_DROP or consensus < MIN_CONSENSUS:
            continue

        median_open = statistics.median(opening for opening, _ in pairs)
        median_current = statistics.median(current for _, current in pairs)
        score = min(10.0, median_drop * 0.325 + consensus * 3.5)
        signals.append(
            MovementSignal(
                period=period_label,
                line=line,
                side=side,
                median_open=median_open,
                median_current=median_current,
                median_drop=median_drop,
                consensus=consensus,
                bookmakers=len(pairs),
                score=score,
            )
        )
    return sorted(signals, key=lambda item: item.score, reverse=True)


def _scrape_match(match_link: str) -> list[MovementSignal]:
    signals: list[MovementSignal] = []
    with tempfile.TemporaryDirectory() as tmp:
        for period, label in PERIODS.items():
            out = Path(tmp) / f"{period}.json"
            try:
                payload = _run_oddsharvester(
                    [
                        "upcoming", "-s", "football",
                        "--match-link", match_link,
                        "-m", "over_under",
                        "--period", period,
                        "--odds-history",
                        "--timezone", "UTC",
                        "--concurrency", "1",
                    ],
                    out,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                logger.warning("Match scrape failed %s / %s: %s", match_link, period, exc)
                continue
            signals.extend(_movement_signals(payload, label))

    return sorted(signals, key=lambda item: item.score, reverse=True)[:MAX_SIGNALS_PER_MATCH]


def _telegram_send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram secrets are not configured")
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if response.ok:
        return True
    logger.error("Telegram error %s: %s", response.status_code, response.text[:300])
    return False


def _format_message(match: dict[str, Any], signals: list[MovementSignal]) -> str:
    home = match.get("home_team") or match.get("home") or "Хозяева"
    away = match.get("away_team") or match.get("away") or "Гости"
    kickoff = match.get("_kickoff_dt")
    kickoff_text = kickoff.strftime("%H:%M UTC") if isinstance(kickoff, datetime) else "скоро"

    lines = [
        "🔥 <b>ПРЕДМАТЧЕВЫЙ ПРОГРУЗ</b>", "",
        f"⚽ <b>{home} — {away}</b>",
        f"🕒 Старт: {kickoff_text}", "",
    ]
    for signal in signals:
        lines += [
            f"<b>{signal.period} · {signal.line} · {signal.side}</b>",
            f"📉 {signal.median_open:.2f} → {signal.median_current:.2f} (-{signal.median_drop:.1f}%)",
            f"🏦 Синхронно: {signal.consensus * 100:.0f}% ({signal.bookmakers} букмекеров)",
            f"🔥 Market Pressure: {signal.score:.1f}/10", "",
        ]
    lines.append("<i>OddsPortal / OddsHarvester · движение рынка, не гарантия исхода</i>")
    return "\n".join(lines)


def main() -> int:
    matches = _collect_upcoming_links()
    sent = 0
    for match in matches:
        link = match.get("match_link") or match.get("match_url")
        if not link:
            continue
        signals = _scrape_match(str(link))
        if not signals:
            logger.info("No qualifying movement: %s", link)
            continue
        if _telegram_send(_format_message(match, signals)):
            sent += 1
    logger.info("Signals sent: %d", sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
