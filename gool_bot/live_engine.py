"""Flashscore live statistics + goal pressure engine."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import async_playwright

logger = logging.getLogger("live_engine")

FLASH_URL = "https://www.flashscore.com/football/"
FSIGN = os.getenv("FLASHSCORE_FSIGN", "SW9D1eZo")
FEED_HOSTS = ("global", "2", "46")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
STATE_FILE = Path(os.getenv("LIVE_STATE_FILE", "live_state.json"))

STAT_MAP = {
    "432": "xg",
    "499": "xgot",
    "12": "possession",
    "34": "shots",
    "13": "shots_on_target",
    "14": "shots_off_target",
    "158": "blocked_shots",
    "461": "shots_inside_box",
    "463": "shots_outside_box",
    "459": "big_chances",
    "16": "corners",
    "471": "touches_box",
    "23": "yellow_cards",
}


@dataclass
class LiveMatch:
    event_id: str
    minute: int
    home: str
    away: str
    home_score: int
    away_score: int
    status: str


@dataclass
class StatsSnapshot:
    ts: int
    minute: int
    values: dict[str, tuple[float, float]]


@dataclass
class GoalPressureResult:
    score: float
    momentum: float
    quality: float
    context: float
    reasons: list[str]


def _to_number(value: str) -> float:
    value = str(value).strip().replace("%", "")
    try:
        return float(value)
    except ValueError:
        return 0.0


def fetch_stats(event_id: str) -> str:
    headers = {
        "User-Agent": UA,
        "x-fsign": FSIGN,
        "Origin": "https://www.flashscore.com",
        "Referer": "https://www.flashscore.com/",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for host in FEED_HOSTS:
        url = f"https://{host}.flashscore.ninja/2/x/feed/df_st_1_{event_id}"
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200 and r.text.strip() and not r.text.lstrip().lower().startswith("<"):
                return r.text
        except requests.RequestException:
            continue
    return ""


def parse_stats(body: str) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for chunk in body.split("~"):
        m = re.search(r"SD(?:÷|¬)(\d+).*?SH(?:÷|¬)([^¬~]+).*?SI(?:÷|¬)([^¬~]+)", chunk)
        if not m:
            continue
        sid, home, away = m.groups()
        name = STAT_MAP.get(sid)
        if name:
            out[name] = (_to_number(home), _to_number(away))
    return out


def load_state() -> dict[str, list[dict[str, Any]]]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_snapshot(event_id: str, snapshot: StatsSnapshot) -> None:
    state = load_state()
    rows = state.setdefault(event_id, [])
    rows.append(asdict(snapshot))
    cutoff = int(time.time()) - 60 * 120
    state[event_id] = [r for r in rows if int(r.get("ts", 0)) >= cutoff][-30:]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _delta(values: dict[str, tuple[float, float]], prev: dict[str, tuple[float, float]], key: str) -> float:
    a = values.get(key, (0.0, 0.0))
    b = prev.get(key, (0.0, 0.0))
    return max(0.0, (a[0] + a[1]) - (b[0] + b[1]))


def calculate_goal_pressure(match: LiveMatch, values: dict[str, tuple[float, float]], previous: dict[str, tuple[float, float]] | None = None) -> GoalPressureResult:
    previous = previous or {}
    xg = sum(values.get("xg", (0, 0)))
    shots = sum(values.get("shots", (0, 0)))
    sot = sum(values.get("shots_on_target", (0, 0)))
    big = sum(values.get("big_chances", (0, 0)))
    inside = sum(values.get("shots_inside_box", (0, 0)))
    touches = sum(values.get("touches_box", (0, 0)))
    corners = sum(values.get("corners", (0, 0)))

    quality = min(100.0, xg * 24 + sot * 5 + big * 10 + inside * 1.7 + touches * 0.45)

    dxg = _delta(values, previous, "xg")
    dshots = _delta(values, previous, "shots")
    dsot = _delta(values, previous, "shots_on_target")
    dbig = _delta(values, previous, "big_chances")
    dinside = _delta(values, previous, "shots_inside_box")
    dtouches = _delta(values, previous, "touches_box")
    dcorners = _delta(values, previous, "corners")
    momentum = min(100.0, dxg * 42 + dshots * 7 + dsot * 13 + dbig * 18 + dinside * 4 + dtouches * 1.4 + dcorners * 5)

    total_goals = match.home_score + match.away_score
    if match.minute <= 45:
        context = 65.0 if total_goals <= 1 else 45.0
    elif match.minute <= 75:
        context = 75.0 if total_goals <= 2 else 55.0
    else:
        context = 70.0 if total_goals <= 3 else 45.0

    base_activity = min(100.0, shots * 2.2 + sot * 5.5 + corners * 1.8)
    score = min(100.0, quality * 0.38 + momentum * 0.37 + base_activity * 0.15 + context * 0.10)

    reasons: list[str] = []
    if dxg >= 0.35:
        reasons.append(f"xG +{dxg:.2f} за последнее окно")
    if dsot >= 2:
        reasons.append(f"+{int(dsot)} удара в створ")
    if dshots >= 4:
        reasons.append(f"+{int(dshots)} ударов")
    if dbig >= 1:
        reasons.append("появился большой момент")
    if dtouches >= 8:
        reasons.append(f"+{int(dtouches)} касаний в штрафной")
    if not reasons and score >= 70:
        reasons.append("высокое суммарное давление")
    return GoalPressureResult(round(score, 1), round(momentum, 1), round(quality, 1), round(context, 1), reasons)


async def discover_live_matches() -> list[LiveMatch]:
    matches: list[LiveMatch] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent=UA, locale="en-GB", timezone_id="UTC", viewport={"width": 1440, "height": 1200})
        page = await context.new_page()
        await page.goto(FLASH_URL, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(4500)
        rows = page.locator("div[id*='g_1_']")
        for i in range(await rows.count()):
            row = rows.nth(i)
            rid = await row.get_attribute("id") or ""
            event_id = rid.split("g_1_", 1)[-1].split("_", 1)[0]
            if len(event_id) != 8:
                continue
            lines = [x.strip() for x in (await row.inner_text()).splitlines() if x.strip()]
            text = " | ".join(lines)
            mm = re.match(r"^(\d{1,2})(?:\+\d+)?\b", lines[0] if lines else "")
            if not mm:
                continue
            minute = int(mm.group(1))
            if minute < 1 or minute > 120:
                continue
            names = []
            for selector in [".event__participant--home", ".event__participant--away"]:
                loc = row.locator(selector)
                if await loc.count():
                    names.append((await loc.first.inner_text()).strip())
            scores = [int(x) for x in lines if re.fullmatch(r"\d+", x)]
            if len(names) >= 2 and len(scores) >= 2:
                matches.append(LiveMatch(event_id, minute, names[0], names[1], scores[-2], scores[-1], text[:180]))
        await browser.close()
    return matches


def get_previous_values(event_id: str, current_minute: int, lookback_minutes: int = 8) -> dict[str, tuple[float, float]] | None:
    state = load_state().get(event_id, [])
    target = current_minute - lookback_minutes
    candidates = [r for r in state if int(r.get("minute", 999)) <= target]
    if not candidates:
        return None
    row = candidates[-1]
    values = row.get("values", {})
    return {k: tuple(v) for k, v in values.items()}
