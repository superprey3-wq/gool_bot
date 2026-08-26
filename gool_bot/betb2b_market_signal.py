"""BetB2B/1xBet market context for GOOL cards.

Read-only helper: market movement is supplementary information only and MUST NOT
create, block or change a GOOL signal probability. 1xBet/Melbet are treated as
one BETB2B source cluster.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional
import logging
import re
import threading
import time

import requests

logger = logging.getLogger("betb2b_market_signal")
BASE = "https://1xbet.fi/service-api"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://1xbet.fi/",
    "Origin": "https://1xbet.fi",
}
_LOCK = threading.Lock()
_POINTS: dict[str, list["MarketPoint"]] = {}
_EVENT_MAP: dict[str, dict] = {}
_LAST_SAMPLE_TS = 0.0
_SAMPLE_MIN_SECONDS = 45.0


@dataclass(frozen=True)
class MarketPoint:
    ts: float
    odds: float
    line: Optional[float] = None
    source: str = "BETB2B"


@dataclass(frozen=True)
class MarketSignal:
    dot: str
    delta_pp: float
    fast: bool
    direction: int  # +1 supports target event, 0 neutral, -1 opposes


def implied_probability(odds: float) -> Optional[float]:
    try:
        x = float(odds)
    except (TypeError, ValueError):
        return None
    return 1.0 / x if x > 1.0 else None


def classify_market(points: Iterable[MarketPoint], *, target_is_selection: bool = True) -> MarketSignal:
    pts = sorted((p for p in points if implied_probability(p.odds) is not None), key=lambda p: p.ts)
    if len(pts) < 2:
        return MarketSignal("🟡", 0.0, False, 0)
    # Last 30 minutes is enough for a card signal and avoids stale morning movement.
    newest = pts[-1].ts
    recent = [p for p in pts if p.ts >= newest - 1800]
    if len(recent) >= 2:
        pts = recent
    a, b = pts[0], pts[-1]
    pa, pb = implied_probability(a.odds), implied_probability(b.odds)
    delta = (pb - pa) * 100.0
    if not target_is_selection:
        delta = -delta
    # Main total moving upward supports more goals; downward opposes them.
    if a.line is not None and b.line is not None and a.line != b.line:
        line_move = b.line - a.line
        if target_is_selection:
            delta += max(-2.0, min(2.0, line_move * 2.0))
    if abs(delta) < 1.5:
        direction, dot = 0, "🟡"
    elif delta > 0:
        direction, dot = 1, "🟢"
    else:
        direction, dot = -1, "🔴"
    fast = abs(delta) >= 4.0 and (b.ts - a.ts) <= 300
    return MarketSignal(dot, round(delta, 2), fast, direction)


def card_market_dot(signal: Optional[MarketSignal]) -> str:
    if signal is None:
        return "🟡"
    # User requested only a private dot on the card. Keep lightning internal for now.
    return signal.dot


def source_cluster(source: str) -> str:
    s = (source or "").lower()
    if "1xbet" in s or "melbet" in s or "betb2b" in s:
        return "BETB2B"
    return (source or "UNKNOWN").upper()


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", str(name or "").lower())
    return " ".join(s.split())


def _key(home: str, away: str) -> str:
    return _norm(home) + "|" + _norm(away)


def _request(path: str, params: dict):
    r = requests.get(BASE + path, params=params, headers=HEADERS, timeout=12)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    body = r.json()
    return body.get("Value")


def _main_over(event: dict) -> Optional[tuple[float, float]]:
    """Return bookmaker-designated or best-balanced full-match OVER line.

    Verified mapping from live probes: G=4 is match totals, T=9 over, T=10 under,
    P is line, C is decimal price. CE=1 marks the preferred/main selection when present.
    """
    ge = event.get("GE") or []
    overs: list[dict] = []
    unders: dict[float, float] = {}
    for group in ge:
        if int(group.get("G") or -1) != 4:
            continue
        for bucket in group.get("E") or []:
            for row in bucket or []:
                try:
                    t = int(row.get("T")); line = float(row.get("P")); odd = float(row.get("C"))
                except (TypeError, ValueError):
                    continue
                if t == 9 and odd > 1:
                    overs.append(row)
                elif t == 10 and odd > 1:
                    unders[line] = odd
    if not overs:
        return None
    preferred = [x for x in overs if int(x.get("CE") or 0) == 1]
    if preferred:
        row = preferred[0]
        return float(row["P"]), float(row["C"])
    # Otherwise choose the line with the most balanced over/under pair.
    scored = []
    for row in overs:
        line = float(row["P"]); odd = float(row["C"]); u = unders.get(line)
        score = abs(odd - 2.0) + (abs(u - 2.0) if u else 3.0)
        scored.append((score, line, odd))
    _, line, odd = min(scored)
    return line, odd


def _append(key: str, point: MarketPoint) -> None:
    with _LOCK:
        xs = _POINTS.setdefault(key, [])
        if xs and xs[-1].odds == point.odds and xs[-1].line == point.line:
            return
        xs.append(point)
        cutoff = point.ts - 6 * 3600
        _POINTS[key] = [p for p in xs[-120:] if p.ts >= cutoff]


def sample_live(force: bool = False) -> int:
    """Sample all current live football matches once; safe to call every GOOL cycle."""
    global _LAST_SAMPLE_TS
    now = time.time()
    with _LOCK:
        if not force and now - _LAST_SAMPLE_TS < _SAMPLE_MIN_SECONDS:
            return 0
        _LAST_SAMPLE_TS = now
    try:
        events = _request("/LiveFeed/Get1x2_VZip", {
            "sports": 1, "count": 1000, "lng": "en", "mode": 4,
            "country": 1, "getEmpty": "true",
        }) or []
    except Exception as exc:
        logger.warning("BETB2B_LIVE_FEED_FAIL %s", exc)
        return 0
    sampled = 0
    for event in events:
        home, away = event.get("O1"), event.get("O2")
        eid = event.get("I")
        if not home or not away or not eid:
            continue
        k = _key(home, away)
        with _LOCK:
            _EVENT_MAP[k] = {"id": eid, "home": home, "away": away, "ts": now}
        try:
            detail = _request("/LiveFeed/GetGameZip", {
                "id": eid, "lng": "en", "cfview": 0, "isSubGames": "true",
                "GroupEvents": "true", "allEventsGroupSubGames": "true",
                "countevents": 250, "grMode": 2,
            })
            if not isinstance(detail, dict):
                continue
            market = _main_over(detail)
            if market:
                line, odd = market
                _append(k, MarketPoint(now, odd, line))
                sampled += 1
        except Exception as exc:
            logger.debug("BETB2B_GAME_FAIL %s %s", eid, exc)
    logger.info("BETB2B_LIVE_SAMPLE events=%d priced=%d", len(events), sampled)
    return sampled


def signal_for_match(home: str, away: str) -> MarketSignal:
    """Return current private market-support signal for a GOOL goal scenario."""
    k = _key(home, away)
    with _LOCK:
        pts = list(_POINTS.get(k) or [])
    return classify_market(pts, target_is_selection=True)


def dot_for_match(home: str, away: str) -> str:
    return card_market_dot(signal_for_match(home, away))
