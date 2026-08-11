"""One-shot live Flashscore stats diagnostic. No Telegram sends."""
from __future__ import annotations

import asyncio
import re
import requests
from datetime import UTC, datetime, timedelta

from prematch_scanner import _discover_from_browser, HEADERS

FSIGN = "SW9D1eZo"
HOSTS = ["global", "2", "46"]
STAT_MAP = {
    "432": "expected_goals",
    "499": "xg_on_target",
    "12": "ball_possession",
    "34": "total_shots",
    "13": "shots_on_target",
    "14": "shots_off_target",
    "158": "blocked_shots",
    "461": "shots_inside_box",
    "463": "shots_outside_box",
    "459": "big_chances",
    "16": "corner_kicks",
    "471": "touches_in_opposition_box",
    "23": "yellow_cards",
}


def fetch_stats(mid: str):
    headers = dict(HEADERS)
    headers.update({"x-fsign": FSIGN, "Origin": "https://www.flashscore.com", "Referer": "https://www.flashscore.com/"})
    for host in HOSTS:
        url = f"https://{host}.flashscore.ninja/2/x/feed/df_st_1_{mid}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            print(f"STAT host={host} status={r.status_code} bytes={len(r.text)}")
            if r.status_code == 200 and r.text.strip() and not r.text.lstrip().lower().startswith("<"):
                return r.text
        except Exception as e:
            print(f"STAT host={host} error={e}")
    return ""


def parse_stats(body: str):
    # Flashscore feed format: stat groups/records use ~ and ¬ separators.
    rows = []
    for chunk in body.split("~"):
        if "SD¬" not in chunk:
            continue
        fields = {}
        toks = chunk.split("¬")
        for i in range(len(toks) - 1):
            key = toks[i][-2:] if len(toks[i]) >= 2 else toks[i]
            if key in {"SD", "SE", "SF", "SG", "SH", "SI"}:
                fields[key] = toks[i + 1]
        sid = fields.get("SD")
        if sid in STAT_MAP:
            rows.append((STAT_MAP[sid], fields))
    return rows


async def main():
    matches = await _discover_from_browser()
    now = datetime.now(UTC)
    print(f"DISCOVERED {len(matches)} matches at {now.isoformat()}")
    # Browser discovery currently parses today's kickoff clock in UTC. Treat fixtures
    # started within last 120 minutes as live candidates; try several until stats exist.
    candidates = []
    for m in matches:
        age = (now - m.kickoff).total_seconds() / 60
        if 0 <= age <= 130:
            candidates.append((age, m))
    candidates.sort(key=lambda x: x[0])
    print(f"LIVE_CANDIDATES {len(candidates)}")
    for age, m in candidates[:20]:
        print(f"TRY {m.event_id} {m.home} - {m.away} started~{age:.0f}m ago")
        body = fetch_stats(m.event_id)
        if not body:
            continue
        print(f"SUCCESS match={m.event_id} body_prefix={body[:220]!r}")
        parsed = parse_stats(body)
        print(f"PARSED_ROWS {len(parsed)}")
        for name, fields in parsed[:40]:
            print(name, fields)
        # Also print short raw fragments for known stat IDs to verify parser mapping.
        for sid, name in STAT_MAP.items():
            pos = body.find(f"SD¬{sid}")
            if pos >= 0:
                print(f"RAW_{name}: {body[max(0,pos-80):pos+180]}")
        return
    print("NO_LIVE_STATS_FOUND")


if __name__ == "__main__":
    asyncio.run(main())
