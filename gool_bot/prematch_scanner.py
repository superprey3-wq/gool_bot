"""Prematch totals movement scanner using Flashscore/LSApp.

Discovery strategy:
1. lightweight Flashscore feed attempts;
2. Flashscore browser DOM/network fallback (GitHub Actions friendly).
Odds come from LSApp where each selection includes opening and current value.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from playwright.async_api import async_playwright

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
FLASH_URLS = ["https://www.flashscore.com/football/", "https://www.flashscore.co.uk/football/"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.flashscore.com/",
}
SCOPE_LABELS = {"FULL_TIME": "Матч", "FIRST_HALF": "1-й тайм", "SECOND_HALF": "2-й тайм"}


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
    values = [day.strftime("%Y%m%d"), day.strftime("%Y-%m-%d"), day.strftime("%d-%m-%Y")]
    result: list[str] = []
    for value in values:
        result += [
            f"https://d.flashscore.com/x/feed/f_{value}",
            f"https://d.flashscore.com/x/feed/dt_{value}",
            f"https://www.flashscore.com/x/feed/f_{value}",
        ]
    return result


def _parse_feed(text: str) -> list[Match]:
    found: dict[str, Match] = {}
    for raw in text.split("~AA¬")[1:]:
        event_id, sep, rest = raw.partition("¬")
        if not sep or len(event_id) != 8 or not event_id.isalnum():
            continue
        tokens = rest.split("¬")
        fields: dict[str, str] = {}
        for i in range(len(tokens) - 1):
            if re.fullmatch(r"[A-Z]{1,3}", tokens[i]):
                fields[tokens[i]] = tokens[i + 1].split("~", 1)[0]
        try:
            kickoff = datetime.fromtimestamp(int(fields.get("AD", "")), UTC)
        except (TypeError, ValueError):
            continue
        home, away = fields.get("AE", "").strip(), fields.get("AF", "").strip()
        if home and away:
            found[event_id] = Match(event_id, home, away, kickoff, fields.get("CX", "") or fields.get("ZA", ""))
    return list(found.values())


def _discover_from_feeds() -> list[Match]:
    now = datetime.now(UTC)
    found: dict[str, Match] = {}
    for day in (now, now + timedelta(days=1)):
        for endpoint in _feed_endpoints(day):
            try:
                r = requests.get(endpoint, headers=HEADERS, timeout=10)
            except requests.RequestException:
                continue
            if r.status_code == 200 and "~AA¬" in r.text:
                parsed = _parse_feed(r.text)
                if parsed:
                    logger.info("Feed discovery: %d matches from %s", len(parsed), endpoint)
                    found.update({m.event_id: m for m in parsed})
                    break
    return list(found.values())


def _parse_clock(text: str, now: datetime) -> datetime | None:
    text = " ".join(text.split())
    # Common Flashscore row forms: HH:MM or DD.MM. HH:MM
    m = re.search(r"(?:(\d{1,2})\.(\d{1,2})\.\s*)?(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    day_s, month_s, hour_s, minute_s = m.groups()
    if day_s and month_s:
        try:
            candidate = datetime(now.year, int(month_s), int(day_s), int(hour_s), int(minute_s), tzinfo=UTC)
        except ValueError:
            return None
        # New-year boundary correction.
        if candidate < now - timedelta(days=180):
            candidate = candidate.replace(year=now.year + 1)
        return candidate
    return now.replace(hour=int(hour_s), minute=int(minute_s), second=0, microsecond=0)


async def _discover_from_browser() -> list[Match]:
    now = datetime.now(UTC)
    found: dict[str, Match] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent=HEADERS["User-Agent"], locale="en-GB", timezone_id="UTC",
            viewport={"width": 1440, "height": 1200},
        )
        page = await context.new_page()
        network_ids: set[str] = set()

        async def capture(response):
            url = response.url
            if "flashscore" not in url and "lsapp" not in url:
                return
            try:
                body = await response.text()
            except Exception:
                return
            network_ids.update(re.findall(r"g_1_([A-Za-z0-9]{8})", body))
            network_ids.update(re.findall(r'"eventId"\s*:\s*"([A-Za-z0-9]{8})"', body))

        page.on("response", capture)

        for url in FLASH_URLS:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=35000)
                await page.wait_for_timeout(4500)
                # Scroll to force lazy-loaded rows.
                for _ in range(4):
                    await page.mouse.wheel(0, 1400)
                    await page.wait_for_timeout(600)
                rows = page.locator("div[id*='g_1_']")
                count = await rows.count()
                logger.info("Flashscore DOM %s: %d rows, network ids=%d", url, count, len(network_ids))
                for i in range(count):
                    row = rows.nth(i)
                    rid = await row.get_attribute("id") or ""
                    match_id = rid.split("g_1_", 1)[-1].split("_", 1)[0]
                    if len(match_id) != 8 or not match_id.isalnum():
                        continue
                    text = (await row.inner_text()).strip()
                    kickoff = _parse_clock(text, now)
                    if not kickoff:
                        continue

                    # Team names are usually participant-name anchors/spans. Fallback to
                    # cleaned row lines when CSS changes.
                    names: list[str] = []
                    for selector in [
                        ".event__participant--home", ".event__participant--away",
                        "[class*='participant--home']", "[class*='participant--away']",
                    ]:
                        loc = row.locator(selector)
                        if await loc.count():
                            value = (await loc.first.inner_text()).strip()
                            if value and value not in names:
                                names.append(value)
                    if len(names) < 2:
                        lines = [x.strip() for x in text.splitlines() if x.strip()]
                        # Remove obvious clock/score/status tokens; first two remaining
                        # alphabetic strings are typically the teams.
                        candidates = [x for x in lines if re.search(r"[A-Za-zА-Яа-я]", x) and not re.fullmatch(r"\d{1,2}:\d{2}", x)]
                        names = candidates[:2]
                    if len(names) >= 2:
                        found[match_id] = Match(match_id, names[0], names[1], kickoff)
                if found:
                    break
            except Exception as exc:
                logger.warning("Flashscore browser discovery failed %s: %s", url, str(exc)[:180])

        # Network-only IDs are useful only if we can resolve metadata. Open their
        # summary pages for IDs not already found; cap to avoid abuse.
        unresolved = [mid for mid in network_ids if mid not in found][:40]
        for mid in unresolved:
            try:
                detail = await context.new_page()
                await detail.goto(f"https://www.flashscore.com/match/{mid}/#/match-summary", wait_until="domcontentloaded", timeout=18000)
                await detail.wait_for_timeout(900)
                body = (await detail.locator("body").inner_text()).strip()
                kickoff = _parse_clock(body, now)
                home_loc = detail.locator(".duelParticipant__home .participant__participantName")
                away_loc = detail.locator(".duelParticipant__away .participant__participantName")
                if kickoff and await home_loc.count() and await away_loc.count():
                    found[mid] = Match(mid, (await home_loc.first.inner_text()).strip(), (await away_loc.first.inner_text()).strip(), kickoff)
                await detail.close()
            except Exception:
                try:
                    await detail.close()
                except Exception:
                    pass

        await browser.close()
    return list(found.values())


def _discover_matches() -> list[Match]:
    now = datetime.now(UTC)
    matches = _discover_from_feeds()
    if not matches:
        logger.info("Feed discovery empty; using Flashscore browser/network fallback")
        try:
            matches = asyncio.run(_discover_from_browser())
        except Exception as exc:
            logger.warning("Browser discovery crashed: %s", exc)
            matches = []
    upcoming = []
    for match in matches:
        minutes = (match.kickoff - now).total_seconds() / 60
        if MIN_MINUTES_TO_KICKOFF <= minutes <= MAX_MINUTES_TO_KICKOFF:
            upcoming.append(match)
    logger.info("Discovered=%d; in %d-%d minute window=%d", len(matches), MIN_MINUTES_TO_KICKOFF, MAX_MINUTES_TO_KICKOFF, len(upcoming))
    return sorted(upcoming, key=lambda m: m.kickoff)


def _fetch_event_odds(event_id: str) -> list[dict[str, Any]]:
    params = {"_hash": "oce", "eventId": event_id, "projectId": "5", "geoIpCode": "US", "geoIpSubdivisionCode": "USCA"}
    try:
        r = requests.get(LSAPP_URL, params=params, headers=HEADERS, timeout=25)
        r.raise_for_status()
        payload = r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("LSApp failed %s: %s", event_id, exc)
        return []
    entries = payload.get("data", {}).get("findOddsByEventId", {}).get("odds", [])
    if isinstance(entries, list):
        logger.info("LSApp %s: %d entries", event_id, len(entries))
        return [x for x in entries if isinstance(x, dict)]
    return []


def _participant_map(entries: list[dict[str, Any]], match: Match) -> dict[Any, str]:
    for entry in entries:
        if entry.get("bettingType") != "HOME_DRAW_AWAY":
            continue
        ids: list[Any] = []
        for item in entry.get("odds", []) or []:
            if isinstance(item, dict):
                pid = item.get("eventParticipantId")
                if pid is not None and pid not in ids:
                    ids.append(pid)
        if len(ids) >= 2:
            return {ids[0]: match.home, ids[1]: match.away}
    return {}


def _extract_signals(entries: list[dict[str, Any]], match: Match) -> list[MovementSignal]:
    participant_names = _participant_map(entries, match)
    buckets: dict[tuple[str, str, str, str], list[tuple[float, float]]] = {}
    types = sorted({str(e.get("bettingType")) for e in entries if e.get("bettingType")})
    logger.info("Market types %s: %s", match.event_id, ", ".join(types[:30]))

    for entry in entries:
        betting_type = str(entry.get("bettingType") or "")
        scope = str(entry.get("bettingScope") or "FULL_TIME")
        items = entry.get("odds") or []
        if not isinstance(items, list):
            continue
        is_total = betting_type == "OVER_UNDER" or ("TOTAL" in betting_type and "SCORE" not in betting_type)
        if not is_total:
            continue
        for item in items:
            if not isinstance(item, dict) or not item.get("active", True):
                continue
            opening, current = _safe_float(item.get("opening")), _safe_float(item.get("value"))
            handicap = item.get("handicap") or {}
            line = handicap.get("value") if isinstance(handicap, dict) else None
            selection = str(item.get("selection") or "").upper()
            if opening is None or current is None or opening <= 1 or current <= 1 or line is None or selection not in {"OVER", "UNDER"}:
                continue
            pid = item.get("eventParticipantId")
            market = "Общий тотал" if pid is None else f"ИТ {participant_names.get(pid, 'команды')}"
            side = "ТБ" if selection == "OVER" else "ТМ"
            buckets.setdefault((market, scope, str(line), side), []).append((opening, current))

    signals: list[MovementSignal] = []
    for (market, scope, line, side), pairs in buckets.items():
        if len(pairs) < MIN_BOOKMAKERS:
            continue
        drops = [((o - c) / o) * 100 for o, c in pairs]
        consensus = sum(d > 0 for d in drops) / len(drops)
        median_drop = statistics.median(drops)
        if median_drop < MIN_MEDIAN_DROP or consensus < MIN_CONSENSUS:
            continue
        signals.append(MovementSignal(
            market, SCOPE_LABELS.get(scope, scope), line, side,
            statistics.median(o for o, _ in pairs), statistics.median(c for _, c in pairs),
            median_drop, consensus, len(pairs), min(10.0, median_drop * 0.325 + consensus * 3.5),
        ))
    return sorted(signals, key=lambda s: s.score, reverse=True)[:MAX_SIGNALS_PER_MATCH]


def _telegram_send(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram secrets missing")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.error("Telegram failed: %s", exc)
        return False
    if r.ok:
        return True
    logger.error("Telegram %s: %s", r.status_code, r.text[:250])
    return False


def _format(match: Match, signals: list[MovementSignal]) -> str:
    lines = ["🔥 <b>ПРЕДМАТЧЕВЫЙ ПРОГРУЗ</b>", "", f"⚽ <b>{match.home} — {match.away}</b>", f"🕒 Старт: {match.kickoff.strftime('%H:%M UTC')}", ""]
    for s in signals:
        lines += [
            f"<b>{s.scope} · {s.market} {s.line} · {s.side}</b>",
            f"📉 {s.median_open:.2f} → {s.median_current:.2f} (-{s.median_drop:.1f}%)",
            f"🏦 Синхронно: {s.consensus * 100:.0f}% ({s.bookmakers} букмекеров)",
            f"🔥 Market Pressure: {s.score:.1f}/10", "",
        ]
    lines.append("<i>Flashscore/LSApp · opening → current</i>")
    return "\n".join(lines)


def main() -> int:
    matches = _discover_matches()
    sent = 0
    for match in matches:
        entries = _fetch_event_odds(match.event_id)
        signals = _extract_signals(entries, match) if entries else []
        if signals and _telegram_send(_format(match, signals)):
            sent += 1
            logger.info("Signal sent %s - %s", match.home, match.away)
        elif entries:
            logger.info("No qualifying movement %s - %s", match.home, match.away)
    logger.info("Signals sent: %d", sent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
