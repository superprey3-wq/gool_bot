"""Isolated Flashscore hockey discovery probe.

Experimental only: does not import or modify the football runtime.
Run: python -m gool_bot.hockey_probe
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from live_engine import _feed

# Flashscore sport id 4 = ice hockey. Keep football's feed untouched.
HOCKEY_MASTER_FEEDS = ("f_4_0_0_en_1", "f_4_0_0_en_2")

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
    # Same feed family as football, but event belongs to hockey.
    summary = _feed(f"df_sui_4_{event_id}") or _feed(f"df_sui_1_{event_id}")
    stats = _feed(f"df_st_4_{event_id}") or _feed(f"df_st_1_{event_id}")
    # Preserve raw stat IDs/names during discovery; do not guess mappings yet.
    stat_rows = []
    for chunk in stats.split("~"):
        m = re.search(r"SD(?:÷|¬)(\d+).*?SE(?:÷|¬)([^¬~]+).*?SH(?:÷|¬)([^¬~]+).*?SI(?:÷|¬)([^¬~]+)", chunk)
        if m:
            stat_rows.append({"id": m.group(1), "name": m.group(2), "home": m.group(3), "away": m.group(4)})
    return {"summary_bytes": len(summary), "stats_bytes": len(stats), "stats": stat_rows}


def main() -> None:
    body = ""
    used = ""
    for path in HOCKEY_MASTER_FEEDS:
        body = _feed(path)
        if body:
            used = path
            break
    if not body:
        print("HOCKEY_PROBE: master feed unavailable")
        return
    matches = parse_master(body)
    live = [m for m in matches if m.coarse_status == "2"]
    print(f"HOCKEY_PROBE feed={used} total={len(matches)} live={len(live)} ts={int(time.time())}")
    for m in live[:25]:
        detail = inspect_event(m.event_id)
        print(f"LIVE {m.event_id} | {m.home} — {m.away} | {m.home_score}:{m.away_score} | AB={m.coarse_status} AC={m.status_code} | {m.league}")
        print(f"  summary={detail['summary_bytes']}B stats={detail['stats_bytes']}B")
        for row in detail["stats"][:20]:
            print(f"  STAT {row['id']} {row['name']}: {row['home']} — {row['away']}")


if __name__ == "__main__":
    main()
