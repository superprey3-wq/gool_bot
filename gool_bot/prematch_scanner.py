"""Prematch totals movement scanner powered by OddsHarvester/OddsPortal.

Runs as a short-lived job (GitHub Actions friendly):
1. collect football matches kicking off soon;
2. scrape Over/Under history for full time, 1st half and 2nd half;
3. detect synchronized bookmaker drops;
4. send only strong signals to Telegram shortly before kickoff.

No live monitoring and no persistent server are required.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prematch_scanner")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# A 5-minute GitHub cron can be delayed, so use a tolerant single-pass window.
MIN_MINUTES_TO_KICKOFF = int(os.getenv("MIN_MINUTES_TO_KICKOFF", "2"))
MAX_MINUTES_TO_KICKOFF = int(os.getenv("MAX_MINUTES_TO_KICKOFF", "9"))

MIN_BOOKMAKERS = int(os.getenv("MIN_BOOKMAKERS", "3"))
MIN_CONSENSUS = float(os.getenv("MIN_CONSENSUS", "0.65"))
MIN_MEDIAN_DROP = float(os.getenv("MIN_MEDIAN_DROP", "8.0"))
MAX_SIGNALS_PER_MATCH = int(os.getenv("MAX_SIGNALS_PER_MATCH", "4"))

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


def run_oddsharvester(args: list[str], output_path: Path) -> Any:
    cmd = ["oddsharvester", *args, "-f", "json", "-o", str(output_path), "--headless"]
    logger.info("Running OddsHarvester: %s", " ".join(cmd[:-2]))
    subprocess.run(cmd, check=True, timeout=240)
    if not output_path.exists():
        return []
    return json.loads(output_path.read_text(encoding="utf-8"))


def collect_records(node: Any) -> list[dict[str, Any]]:
    """Find match-like dictionaries regardless of OddsHarvester JSON wrapper shape."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if any(k in node for k in ("home_team", "away_team", "match_link", "kickoff_utc")):
            found.append(node)
        for value in node.values():
            found.extend(collect_records(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(collect_records(value))
    return found


def parse_kickoff(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip().replace(" UTC", "+00:00")
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except ValueError:
            pass
    return None


def upcoming_links() -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    dates = {now.strftime("%Y%m%d")}
    # Near midnight, the kickoff may belong to the next UTC date.
    dates.add(datetime.fromtimestamp(now.timestamp() + 3600 * 12, UTC).strftime("%Y%m%d"))

    matches: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for date in dates:
            out = Path(tmp) / f"links-{date}.json"
            try:
                payload = run_oddsharvester(
                    [
                        "upcoming", "-s", "football", "-d", date,
                        "--links-only", "--kickoff-within-hours", "0.25",
                        "--timezone", "UTC",
                    ],
                    out,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                logger.warning("Link collection failed for %s: %s", date, exc)
                continue

            for row in collect_records(payload):
                link = row.get("match_link") or row.get("match_url")
                kickoff = parse_kickoff(row.get("kickoff_utc") or row.get("match_date"))
                if not link or not kickoff:
                    continue
                minutes = (kickoff - now).total_seconds() / 60
                if MIN_MINUTES_TO_KICKOFF <= minutes <= MAX_MINUTES_TO_KICKOFF:
                    row["_kickoff_dt"] = kickoff
                    matches[link] = row
    return list(matches.values())


def bookmaker_entries(node: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("bookmaker_name") and node.get("odds_history_data"):
            result.append(node)
        for value in node.values():
            result.extend(bookmaker_entries(value))
    elif isinstance(node, list):
        for value in node:
            result.extend(bookmaker_entries(value))
    return result


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def opening_from_history(history_item: Any) -> float | None:
    if not isinstance(history_item, dict):
        return None
    opening = history_item.get("opening_odds")
    if isinstance(opening, dict):
        return number(opening.get("odds"))
    return None


def movement_signals(payload: Any, period_label: str) -> list[MovementSignal]:
    # key = (line, side), value = (opening, current) per bookmaker
    buckets: dict[tuple[str, str], list[tuple[float, float]]] = {}

    for entry in bookmaker_entries(payload):
        histories = entry.get("odds_history_data") or []
        if not isinstance(histories, list):
            continue
        line = str(entry.get("submarket_name") or entry.get("market") or "Over/Under")

        # OddsHarvester stores Over then Under in the same order as the odds columns.
        for index, (side, current_key) in enumerate((("ТБ", "odds_over"), ("ТМ", "odds_under"))):
            current = number(entry.get(current_key))
            if current is None or index >= len(histories):
                continue
            opening = opening_from_history(histories[index])
            if opening is None or opening <= 1 or current <= 1:
                continue
            buckets.setdefault((line, side), []).append((opening, current))

    signals: list[MovementSignal] = []
    for (line, side), pairs in buckets.items():
        if len(pairs) < MIN_BOOKMAKERS:
            continue
        drops = [((op - cur) / op) * 100 for op, cur in pairs]
        down_count = sum(1 for drop in drops if drop > 0)
        consensus = down_count / len(drops)
        median_drop = statistics.median(drops)
        if median_drop < MIN_MEDIAN_DROP or consensus < MIN_CONSENSUS:
            continue

        median_open = statistics.median(op for op, _ in pairs)
        median_current = statistics.median(cur for _, cur in pairs)
        # 0..10-ish score: movement magnitude + cross-bookmaker agreement.
        score = min(10.0, median_drop / 2.0 * 0.65 + consensus * 10 * 0.35)
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
    return sorted(signals, key=lambda x: x.score, reverse=True)


def scrape_match(match_link: str) -> list[MovementSignal]:
    signals: list[MovementSignal] = []
    with tempfile.TemporaryDirectory() as tmp:
        for period, label in PERIODS.items():
            out = Path(tmp) / f"{period}.json"
            try:
                payload = run_oddsharvester(
                    [
                        "upcoming", "-s", "football", "--match-link", match_link,
                        "-m", "over_under", "--period", period,
                        "--odds-history", "--timezone", "UTC", "--concurrency", "1",
                    ],
                    out,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                logger.warning("Scrape failed for %s / %s: %s", match_link, period, exc)
                continue
            signals.extend(movement_signals(payload, label))
    return sorted(signals, key=lambda x: x.score, reverse=True)[:MAX_SIGNALS_PER_MATCH]


def telegram_send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram secrets are not configured")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
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
    logger.error("Telegram error %s: %s", response.status_code, response.text[:500])
    return False


def format_message(match: dict[str, Any], signals: list[MovementSignal]) -> str:
    home = match.get("home_team") or match.get("home") or "Хозяева"
    away = match.get("away_team") or match.get("away") or "Гости"
    kickoff = match.get("_kickoff_dt")
    kickoff_text = kickoff.strftime("%H:%M UTC") if isinstance(kickoff, datetime) else "скоро"

    lines = [
        "🔥 <b>ПРЕДМАТЧЕВЫЙ ПРОГРУЗ</b>",
        "",
        f"⚽ <b>{home} — {away}</b>",
        f"🕒 Старт: {kickoff_text}",
        "",
    ]
    for signal in signals:
        lines.extend(
            [
                f"<b>{signal.period} · {signal.line} · {signal.side}</b>",
                f"📉 {signal.median_open:.2f} → {signal.median_current:.2f}  (-{signal.median_drop:.1f}%)",
                f"🏦 Синхронно: {signal.consensus * 100:.0f}% букмекеров ({signal.bookmakers})",
                f"🔥 Market Pressure: {signal.score:.1f}/10",
                "",
            ]
        )
    lines.append("<i>Источник: OddsPortal / OddsHarvester. Это сигнал движения рынка, не гарантия исхода.</i>")
    return "\n".join(lines)


def main() -> int:
    matches = upcoming_links()
    logger.info("Matches in signal window: %d", len(matches))
    sent = 0
    for match in matches:
        link = match.get("match_link") or match.get("match_url")
        if not link:
            continue
        signals = scrape_match(link)
        if not signals:
            logger.info("No strong totals movement: %s", link)
            continue
        if telegram_send(format_message(match, signals)):
            sent += 1
    logger.info("Signals sent: %d", sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
