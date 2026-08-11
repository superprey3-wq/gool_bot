"""Full-world LIVE discovery from Flashscore master football feed.

The web page rendered on GitHub Actions is region-filtered. The master feed
f_1_0_0_en_1 contains the broader match list; AB=2 marks currently live events.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from live_engine import LiveMatch, _feed

logger = logging.getLogger("live_feed_discovery")

LIVE_COARSE_STATUS = "2"  # Flashscore AB: 1 scheduled, 2 live, 3 finished
FIRST_HALF_STATUS = "12"
SECOND_HALF_STATUS = "13"
HALFTIME_STATUS = "38"


def _fields(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in raw.split("¬"):
        if "÷" not in token:
            continue
        key, value = token.split("÷", 1)
        if key and key not in out:
            out[key] = value
    return out


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _minute(fields: dict[str, str], now: int) -> tuple[int, bool]:
    """Derive displayed match minute from Flashscore period status + AO timestamp."""
    ac = fields.get("AC", "")
    ao = _as_int(fields.get("AO"))
    ad = _as_int(fields.get("AD"))

    if ac == HALFTIME_STATUS:
        return 45, True

    if ac == FIRST_HALF_STATUS:
        base = ao or ad
        elapsed = max(0, now - base) if base else 0
        return max(1, min(45, elapsed // 60 + 1)), False

    if ac == SECOND_HALF_STATUS:
        base = ao or ad
        elapsed = max(0, now - base) if base else 0
        return max(46, min(90, 45 + elapsed // 60 + 1)), False

    # Rare live states (stoppage/extra time/penalties). Keep the event instead
    # of losing coverage. AO is normally the current-period start timestamp.
    if ao:
        elapsed = max(0, now - ao) // 60 + 1
        # AC=6 has been observed around extra-time matches.
        if ac == "6":
            return max(91, min(130, 90 + elapsed)), False
    if ad:
        elapsed = max(1, (now - ad) // 60 + 1)
        # Remove an approximate halftime interval for fallback display only.
        if elapsed > 60:
            elapsed -= 15
        return max(1, min(130, elapsed)), False
    return 1, False


def parse_master_live(body: str) -> list[LiveMatch]:
    now = int(time.time())
    matches: list[LiveMatch] = []
    current_league = ""

    for chunk in body.split("~"):
        if not chunk:
            continue
        if chunk.startswith("ZA÷"):
            league_fields = _fields(chunk)
            current_league = league_fields.get("ZA", "").strip()
            continue
        if not chunk.startswith("AA÷"):
            continue

        event_id, sep, rest = chunk[3:].partition("¬")
        if not sep or len(event_id) != 8 or not event_id.isalnum():
            continue
        fields = _fields(rest)
        if fields.get("AB") != LIVE_COARSE_STATUS:
            continue

        home = (fields.get("AE") or fields.get("CX") or "").strip()
        away = (fields.get("AF") or "").strip()
        if not home or not away:
            continue

        home_score = _as_int(fields.get("AG"), _as_int(fields.get("AT")))
        away_score = _as_int(fields.get("AH"), _as_int(fields.get("AU")))
        minute, is_halftime = _minute(fields, now)
        ac = fields.get("AC", "")
        status = f"feed AB=2 AC={ac}"

        matches.append(
            LiveMatch(
                event_id=event_id,
                minute=minute,
                home=home,
                away=away,
                home_score=home_score,
                away_score=away_score,
                status=status,
                league=current_league,
                is_halftime=is_halftime,
            )
        )

    # Event IDs are stable; remove any accidental duplicate rows.
    unique = {m.event_id: m for m in matches}
    return list(unique.values())


async def discover_live_matches() -> list[LiveMatch]:
    body = _feed("f_1_0_0_en_1")
    if body:
        matches = parse_master_live(body)
        if matches:
            logger.info("MASTER-FEED LIVE: %d матчей (AB=2)", len(matches))
            return matches
        logger.warning("Master feed loaded but no AB=2 events parsed")

    # Fallback to the proven browser parser if master feed is temporarily unavailable.
    from live_engine import discover_live_matches as browser_discovery

    logger.warning("Master feed unavailable; fallback to browser LIVE discovery")
    return await browser_discovery()
