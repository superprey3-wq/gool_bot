"""Prematch totals movement scanner using Flashscore/LSApp.

The scanner is a short-lived GitHub Actions job. It discovers today's football
matches from Flashscore feeds, fetches bookmaker odds from the LSApp GraphQL
endpoint and compares opening odds with current odds. No persistent server and
no live-match monitoring are required.
"""
from __future__ import annotations

import logging
import os
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

LSAPP_URL = "https://global.ds.lsapp.eu/odds/pq_graphql"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.flashscore.com/",
}

SCOPE_LABELS = {
    "FULL_TIME": "Матч",
    "FIRST_HALF": "1-й тайм",
    "SECOND_HALF": "2-й тайм",
}


@dataclass
class Match:
    event_id: str
    home: str
    away: str
    kickoff: datetime
    league: str = ""


@dataclass
class MovementSignal:
    market: str
    scope: str
    line: str
    side: str
    median_open: float
    median_current: float
    median_drop: float
    consensus: float
    bookmakers: int
    score: float


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _feed_endpoints(day: datetime) -> list[str]:
    # Flashscore has used several feed URL/date variants over time. Try all
    # inexpensive HTTP forms before giving up.
    values = [day.strftime("%Y%m%d"), day.strftime("%Y-%m-%d"), day.strftime("%d-%m-%Y")]
    endpoints: list[str] = []
    for value in values:
        endpoints.extend([
            f"https://d.flashscore.com/x/feed/f_{value}",
            f"https://d.flashscore.com/x/feed/dt_{value}",
            f"https://www.flashscore.com/x/feed/f_{value}",
        ])
    return endpoints


def _parse_feed(text: str) -> list[Match]:
    matches: dict[str, Match] = {}
    if "~AA¬" not in text:
        return []

    for raw in text.split("~AA¬")[1:]:
        event_id, sep, rest = raw.partition("¬")
        event_id = event_id.strip()
        if not sep or len(event_id) != 8 or not event_id.isalnum():
            continue

        fields: dict[str, str] = {}
        # Flashscore feed format is CODE¬VALUE¬CODE¬VALUE...
        tokens = rest.split("¬")
        for idx in range(len(tokens) - 1):
            code = tokens[idx]
            if re.fullmatch(r"[A-Z]{1,3}", code):
                fields[code] = tokens[idx + 1].split("~", 1)[0]

        ts_raw = fields.get("AD", "")
        try:
            ts = int(ts_raw)
        except (TypeError, ValueError):
            continue
        kickoff = datetime.fromtimestamp(ts, UTC)

        home = fields.get("AE", "").strip()
        away = fields.get("AF", "").strip()
        if not home or not away:
            continue

        league = fields.get("CX", "") or fields.get("ZA", "")
        matches[event_id] = Match(event_id=event_id, home=home, away=away, kickoff=kickoff, league=league)

    return list(matches.values())


def _discover_matches() -> list[Match]:
    now = datetime.now(UTC)
    days = [now, now + timedelta(days=1)]
    discovered: dict[str, Match] = {}

    for day in days:
        for endpoint in _feed_endpoints(day):
            try:
                response = requests.get(endpoint, headers=HEADERS, timeout=15)
            except requests.RequestException:
                continue
            if response.status_code != 200 or len(response.text) < 50:
                continue
            parsed = _parse_feed(response.text)
            if parsed:
                logger.info("Flashscore feed OK: %s -> %d matches", endpoint, len(parsed))
                for match in parsed:
                    discovered[match.event_id] = match
                break

    # Precise signal window filtering is intentionally local.
    upcoming: list[Match] = []
    for match in discovered.values():
        minutes = (match.kickoff - now).total_seconds() / 60
        if MIN_MINUTES_TO_KICKOFF <= minutes <= MAX_MINUTES_TO_KICKOFF:
            upcoming.append(match)

    logger.info("Discovered=%d, in %d-%d minute window=%d", len(discovered), MIN_MINUTES_TO_KICKOFF, MAX_MINUTES_TO_KICKOFF, len(upcoming))
    return sorted(upcoming, key=lambda item: item.kickoff)


def _fetch_event_odds(event_id: str) -> list[dict[str, Any]]:
    params = {
        "_hash": "oce",
        "eventId": event_id,
        "projectId": "5",
        "geoIpCode": "US",
        "geoIpSubdivisionCode": "USCA",
    }
    try:
        response = requests.get(LSAPP_URL, params=params, headers=HEADERS, timeout=25)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("LSApp failed for %s: %s", event_id, exc)
        return []

    entries = payload.get("data", {}).get("findOddsByEventId", {}).get("odds", [])
    if not isinstance(entries, list):
        return []
    logger.info("LSApp %s: %d odds entries", event_id, len(entries))
    return [entry for entry in entries if isinstance(entry, dict)]


def _participant_map(entries: list[dict[str, Any]], match: Match) -> dict[Any, str]:
    # The upstream Flashscore scraper uses participant order from 1X2 odds as
    # home then away. Do the same, but only for labelling team-total markets.
    for entry in entries:
        if entry.get("bettingType") != "HOME_DRAW_AWAY":
            continue
        ids: list[Any] = []
        for item in entry.get("odds", []) or []:
            participant_id = item.get("eventParticipantId") if isinstance(item, dict) else None
            if participant_id is not None and participant_id not in ids:
                ids.append(participant_id)
        if len(ids) >= 2:
            return {ids[0]: match.home, ids[1]: match.away}
    return {}


def _signal_score(drop: float, consensus: float) -> float:
    return min(10.0, drop * 0.325 + consensus * 3.5)


def _extract_signals(entries: list[dict[str, Any]], match: Match) -> list[MovementSignal]:
    participant_names = _participant_map(entries, match)
    # key -> [(opening, current), ...] from independent bookmakers
    buckets: dict[tuple[str, str, str, str], list[tuple[float, float]]] = {}
    unknown_types: set[str] = set()

    for entry in entries:
        betting_type = str(entry.get("bettingType") or "")
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        bookmaker_id = entry.get("bookmakerId")
        odds_items = entry.get("odds") or []
        if bookmaker_id is None or not isinstance(odds_items, list):
            continue

        # General total market. If an eventParticipantId is present, treat it
        # as an individual/team total; otherwise it is the ordinary match total.
        is_total = betting_type == "OVER_UNDER" or ("TOTAL" in betting_type and "SCORE" not in betting_type)
        if not is_total:
            if betting_type:
                unknown_types.add(betting_type)
            continue

        for item in odds_items:
            if not isinstance(item, dict) or not item.get("active", True):
                continue
            opening = _safe_float(item.get("opening"))
            current = _safe_float(item.get("value"))
            handicap = item.get("handicap") or {}
            line_value = handicap.get("value") if isinstance(handicap, dict) else None
            selection = str(item.get("selection") or "").upper()
            participant_id = item.get("eventParticipantId")
            if opening is None or current is None or opening <= 1 or current <= 1:
                continue
            if line_value is None or selection not in {"OVER", "UNDER"}:
                continue

            if participant_id is not None:
                team_name = participant_names.get(participant_id, "Командный тотал")
                market = f"ИТ {team_name}"
            else:
                market = "Общий тотал"

            side = "ТБ" if selection == "OVER" else "ТМ"
            key = (market, scope, str(line_value), side)
            buckets.setdefault(key, []).append((opening, current))

    if unknown_types:
        logger.info("Other LSApp market types: %s", ", ".join(sorted(unknown_types)[:20]))

    signals: list[MovementSignal] = []
    for (market, scope, line, side), pairs in buckets.items():
        if len(pairs) < MIN_BOOKMAKERS:
            continue
        drops = [((opening - current) / opening) * 100 for opening, current in pairs]
        consensus = sum(drop > 0 for drop in drops) / len(drops)
        median_drop = statistics.median(drops)
        if median_drop < MIN_MEDIAN_DROP or consensus < MIN_CONSENSUS:
            continue

        signals.append(MovementSignal(
            market=market,
            scope=SCOPE_LABELS.get(scope, scope),
            line=line,
            side=side,
            median_open=statistics.median(opening for opening, _ in pairs),
            median_current=statistics.median(current for _, current in pairs),
            median_drop=median_drop,
            consensus=consensus,
            bookmakers=len(pairs),
            score=_signal_score(median_drop, consensus),
        ))

    return sorted(signals, key=lambda item: item.score, reverse=True)[:MAX_SIGNALS_PER_MATCH]


def _telegram_send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram secrets are not configured")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.error("Telegram request failed: %s", exc)
        return False
    if response.ok:
        return True
    logger.error("Telegram error %s: %s", response.status_code, response.text[:300])
    return False


def _format_message(match: Match, signals: list[MovementSignal]) -> str:
    lines = [
        "🔥 <b>ПРЕДМАТЧЕВЫЙ ПРОГРУЗ</b>", "",
        f"⚽ <b>{match.home} — {match.away}</b>",
        f"🕒 Старт: {match.kickoff.strftime('%H:%M UTC')}",
    ]
    if match.league:
        lines.append(f"🏆 {match.league}")
    lines.append("")

    for signal in signals:
        lines.extend([
            f"<b>{signal.scope} · {signal.market} {signal.line} · {signal.side}</b>",
            f"📉 {signal.median_open:.2f} → {signal.median_current:.2f} (-{signal.median_drop:.1f}%)",
            f"🏦 Синхронно: {signal.consensus * 100:.0f}% ({signal.bookmakers} букмекеров)",
            f"🔥 Market Pressure: {signal.score:.1f}/10", "",
        ])

    lines.append("<i>Flashscore/LSApp · opening → current, движение рынка не гарантирует исход</i>")
    return "\n".join(lines)


def main() -> int:
    matches = _discover_matches()
    sent = 0
    for match in matches:
        entries = _fetch_event_odds(match.event_id)
        if not entries:
            continue
        signals = _extract_signals(entries, match)
        if not signals:
            logger.info("No qualifying movement: %s - %s", match.home, match.away)
            continue
        if _telegram_send(_format_message(match, signals)):
            sent += 1
            logger.info("Signal sent: %s - %s", match.home, match.away)
    logger.info("Signals sent: %d", sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
