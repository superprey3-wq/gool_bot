"""Standalone Flashscore hockey discovery probe.

Experimental only: never imports or modifies the football runtime.
Run from gool_bot/: python hockey_probe.py
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

import requests

FSIGN = os.getenv("FLASHSCORE_FSIGN", "SW9D1eZo")
FEED_HOSTS = ("global", "2", "46")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
HOCKEY_MASTER_FEEDS = ("f_4_0_0_en_1", "f_4_0_0_en_2")


def feed(path: str) -> str:
    headers = {
        "User-Agent": UA,
        "x-fsign": FSIGN,
        "Origin": "https://www.flashscore.com",
        "Referer": "https://www.flashscore.com/hockey/",
        "Accept": "*/*",
    }
    for host in FEED_HOSTS:
        try:
            r = requests.get(f"https://{host}.flashscore.ninja/2/x/feed/{path}", headers=headers, timeout=15)
            if r.status_code == 200 and r.text.strip() and not r.text.lstrip().lower().startswith("<"):
                return r.text
        except requests.RequestException:
            pass
    return ""


@dataclass
class HockeyMatch:
    event_id: str
    home: str
    away: str
    home_score: int
    away_score: int
    status_code: str
    coarse_status: str
    league: str = ""


def fields(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in raw.split("¬"):
        if "÷" in token:
            key, value = token.split("÷", 1)
            if key and key not in out:
                out[key] = value
    return out


def as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def parse_master(body: str) -> list[HockeyMatch]:
    current_league = ""
    matches: list[HockeyMatch] = []
    for chunk in body.split("~"):
        if chunk.startswith("ZA÷"):
            current_league = fields(chunk).get("ZA", "").strip()
            continue
        if not chunk.startswith("AA÷"):
            continue
        event_id, sep, rest = chunk[3:].partition("¬")
        if not sep or len(event_id) != 8 or not event_id.isalnum():
            continue
        f = fields(rest)
        home = (f.get("AE") or f.get("CX") or "").strip()
        away = (f.get("AF") or "").strip()
        if not home or not away:
            continue
        matches.append(HockeyMatch(
            event_id=event_id,
            home=home,
            away=away,
            home_score=as_int(f.get("AG"), as_int(f.get("AT"))),
            away_score=as_int(f.get("AH"), as_int(f.get("AU"))),
            status_code=f.get("AC", ""),
            coarse_status=f.get("AB", ""),
            league=current_league,
        ))
    return list({m.event_id: m for m in matches}.values())


def inspect_event(event_id: str) -> dict:
    # Probe both observed feed families during discovery. Hockey-specific paths win.
    summary = feed(f"df_sui_4_{event_id}") or feed(f"df_sui_1_{event_id}")
    stats = feed(f"df_st_4_{event_id}") or feed(f"df_st_1_{event_id}")
    stat_rows = []
    for chunk in stats.split("~"):
        m = re.search(r"SD(?:÷|¬)(\d+).*?SE(?:÷|¬)([^¬~]+).*?SH(?:÷|¬)([^¬~]+).*?SI(?:÷|¬)([^¬~]+)", chunk)
        if m:
            stat_rows.append({"id": m.group(1), "name": m.group(2), "home": m.group(3), "away": m.group(4)})
    # Keep raw status/event clues so we can map P1/P2/P3/INT/OT/SO from real data.
    clues = []
    for pattern in (r"AC÷[^¬~]+", r"AB÷[^¬~]+", r"AD÷[^¬~]+", r"IB÷[^¬~]+", r"IBX÷[^¬~]+", r"INX÷[^¬~]+", r"IOX÷[^¬~]+"):
        clues.extend(re.findall(pattern, summary)[:20])
    return {"summary_bytes": len(summary), "stats_bytes": len(stats), "stats": stat_rows, "clues": clues[:50]}


def main() -> None:
    body = ""
    used = ""
    for path in HOCKEY_MASTER_FEEDS:
        body = feed(path)
        if body:
            used = path
            break
    if not body:
        raise RuntimeError("HOCKEY_PROBE: master feed unavailable")
    matches = parse_master(body)
    live = [m for m in matches if m.coarse_status == "2"]
    print(f"HOCKEY_PROBE feed={used} total={len(matches)} live={len(live)} ts={int(time.time())}")
    sample = live[:25] if live else matches[:10]
    for m in sample:
        detail = inspect_event(m.event_id)
        tag = "LIVE" if m.coarse_status == "2" else "MATCH"
        print(f"{tag} {m.event_id} | {m.home} — {m.away} | {m.home_score}:{m.away_score} | AB={m.coarse_status} AC={m.status_code} | {m.league}")
        print(f"  summary={detail['summary_bytes']}B stats={detail['stats_bytes']}B")
        if detail["clues"]:
            print("  CLUES " + " | ".join(detail["clues"]))
        for row in detail["stats"][:30]:
            print(f"  STAT {row['id']} {row['name']}: {row['home']} — {row['away']}")
    if not matches:
        raise RuntimeError("HOCKEY_PROBE: feed returned no parseable hockey matches")


if __name__ == "__main__":
    main()
