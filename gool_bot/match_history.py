"""Recent-form + H2H context for a Flashscore event.

Uses the same internal Flashscore feed as the live engine:
  df_hh_1_<eventId>

The feed is split into KB-labelled sections such as
"Last matches: Team" and a head-to-head section. We only use finished rows and
keep a small recent sample so LIVE signal generation remains fast.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_engine import _feed


@dataclass
class PastMatch:
    home: str
    away: str
    home_goals: int
    away_goals: int
    competition: str = ""
    timestamp: int = 0

    @property
    def total(self) -> int:
        return self.home_goals + self.away_goals


@dataclass
class HistoryContext:
    home_recent: list[PastMatch]
    away_recent: list[PastMatch]
    h2h: list[PastMatch]


def _fields(record: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in record.split("¬"):
        if "÷" not in part:
            continue
        key, value = part.split("÷", 1)
        if key and key not in out:
            out[key] = value
    return out


def _norm(value: str) -> str:
    return " ".join((value or "").replace("*", "").lower().split())


def _past(fields: dict[str, str]) -> PastMatch | None:
    # AC=3 is a finished event in these feeds.
    if fields.get("AC") not in {"3", "36", "37"}:
        return None
    try:
        hg = int(float(fields.get("KU", "")))
        ag = int(float(fields.get("KT", "")))
    except (TypeError, ValueError):
        return None
    home = (fields.get("FH") or fields.get("KJ") or "").replace("*", "").strip()
    away = (fields.get("FK") or fields.get("KK") or "").replace("*", "").strip()
    if not home or not away:
        return None
    try:
        ts = int(float(fields.get("KC", "0") or 0))
    except (TypeError, ValueError):
        ts = 0
    return PastMatch(home, away, hg, ag, fields.get("KF", ""), ts)


def fetch_match_history(event_id: str, home: str, away: str, limit: int = 5) -> HistoryContext:
    body = _feed(f"df_hh_1_{event_id}")
    if not body:
        return HistoryContext([], [], [])

    hn, an = _norm(home), _norm(away)
    section = ""
    home_rows: list[PastMatch] = []
    away_rows: list[PastMatch] = []
    h2h_rows: list[PastMatch] = []

    for record in body.split("~"):
        if not record:
            continue
        fields = _fields(record)
        if "KB" in fields:
            title = _norm(fields.get("KB", ""))
            if title.startswith("last matches:"):
                team_name = title.split(":", 1)[1].strip() if ":" in title else ""
                if team_name and (team_name in hn or hn in team_name):
                    section = "home"
                elif team_name and (team_name in an or an in team_name):
                    section = "away"
                else:
                    section = ""
            elif any(key in title for key in ("head-to-head", "head to head", "h2h", "meetings")):
                section = "h2h"
            else:
                section = ""
            continue

        row = _past(fields)
        if not row:
            continue
        if section == "home" and len(home_rows) < limit:
            home_rows.append(row)
        elif section == "away" and len(away_rows) < limit:
            away_rows.append(row)
        elif section == "h2h" and len(h2h_rows) < limit:
            h2h_rows.append(row)

    # Some locales/headings can differ. Recover H2H rows by exact participants if
    # the labelled section was not recognised.
    if not h2h_rows:
        for record in body.split("~"):
            fields = _fields(record)
            row = _past(fields)
            if not row:
                continue
            names = {_norm(row.home), _norm(row.away)}
            if hn in names and an in names:
                h2h_rows.append(row)
                if len(h2h_rows) >= limit:
                    break

    return HistoryContext(home_rows, away_rows, h2h_rows)


def _stats(rows: list[PastMatch]) -> dict[str, float]:
    if not rows:
        return {"n": 0, "avg_total": 0.0, "over25": 0.0, "over35": 0.0, "over45": 0.0, "btts": 0.0}
    n = len(rows)
    return {
        "n": n,
        "avg_total": sum(r.total for r in rows) / n,
        "over25": sum(r.total >= 3 for r in rows) / n,
        "over35": sum(r.total >= 4 for r in rows) / n,
        "over45": sum(r.total >= 5 for r in rows) / n,
        "btts": sum(r.home_goals > 0 and r.away_goals > 0 for r in rows) / n,
    }


def analyse_history(ctx: HistoryContext) -> dict[str, Any]:
    home = _stats(ctx.home_recent)
    away = _stats(ctx.away_recent)
    h2h = _stats(ctx.h2h)
    weighted: list[tuple[float, float]] = []
    if home["n"]:
        weighted.append((home["avg_total"], 1.0))
    if away["n"]:
        weighted.append((away["avg_total"], 1.0))
    if h2h["n"]:
        weighted.append((h2h["avg_total"], 0.7))
    avg = sum(v * w for v, w in weighted) / sum(w for _, w in weighted) if weighted else 0.0
    return {"home": home, "away": away, "h2h": h2h, "historical_avg_total": avg}
