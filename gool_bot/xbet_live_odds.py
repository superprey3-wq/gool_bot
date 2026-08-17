"""Read-only 1xBet LiveFeed probe for GOOL shadow testing.

This module never changes CORE decisions. It only matches current Flashscore
LIVE games to 1xBet and reports whether a live event + detailed market payload
can be fetched. It is intentionally defensive because 1xBet's public LiveFeed
is undocumented and may vary by domain/region.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

import requests

logger = logging.getLogger("xbet_live_odds")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
ROOTS = tuple(x.strip().rstrip("/") for x in os.getenv(
    "XBET_LIVE_ROOTS",
    "https://1xbet.com/LiveFeed,https://1xbet.fi/LiveFeed",
).split(",") if x.strip())
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://1xbet.com/",
}
TIMEOUT = float(os.getenv("XBET_TIMEOUT", "10"))


def _get(method: str, params: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    last_error = None
    for root in ROOTS:
        url = f"{root}/{method}"
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                last_error = f"{root}: HTTP {r.status_code}"
                continue
            data = r.json()
            if isinstance(data, dict) and "Value" in data:
                return data, root, None
            last_error = f"{root}: JSON without Value"
        except (requests.RequestException, ValueError) as exc:
            last_error = f"{root}: {type(exc).__name__}: {exc}"
    return {}, "", last_error


def fetch_live_football() -> tuple[list[dict[str, Any]], str, str | None]:
    data, root, err = _get("Get1x2_VZip", {
        "sports": 1,
        "count": 1000,
        "lng": "en",
        "mode": 4,
        "country": 1,
        "getEmpty": "true",
    })
    value = data.get("Value") if isinstance(data, dict) else None
    return (value if isinstance(value, list) else []), root, err


def fetch_game(event_id: Any) -> tuple[dict[str, Any], str, str | None]:
    data, root, err = _get("GetGameZip", {
        "id": event_id,
        "lng": "en",
        "cfview": 0,
        "isSubGames": "true",
        "GroupEvents": "true",
        "allEventsGroupSubGames": "true",
        "countevents": 250,
        "grMode": 2,
    })
    value = data.get("Value") if isinstance(data, dict) else None
    return (value if isinstance(value, dict) else {}), root, err


def _norm(text: Any) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("women", " w ").replace("ladies", " w ")
    s = re.sub(r"\b(fc|fk|cf|sc|afc|club|football|futbol|soccer)\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _sim(a: Any, b: Any) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    seq = SequenceMatcher(None, a, b).ratio()
    return max(jac, seq)


def match_event(home: str, away: str, events: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float, bool]:
    best = None
    best_score = 0.0
    reversed_order = False
    for e in events:
        h, a = e.get("O1") or e.get("O1E"), e.get("O2") or e.get("O2E")
        normal = (_sim(home, h) + _sim(away, a)) / 2
        rev = (_sim(home, a) + _sim(away, h)) / 2
        score, is_rev = (rev, True) if rev > normal else (normal, False)
        if score > best_score:
            best, best_score, reversed_order = e, score, is_rev
    if best_score < 0.62:
        return None, best_score, reversed_order
    return best, best_score, reversed_order


def _collect_bet_nodes(obj: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        # 1xBet compact market selections commonly expose C=coefficient,
        # P=parameter/line and T=selection type. Keep raw values for diagnosis.
        if "C" in obj and ("T" in obj or "P" in obj):
            try:
                odd = float(obj.get("C"))
            except (TypeError, ValueError):
                odd = 0.0
            if odd > 1.0:
                out.append({k: obj.get(k) for k in ("T", "C", "P", "G", "CE", "CV", "N") if k in obj})
        for v in obj.values():
            _collect_bet_nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_bet_nodes(v, out)


def market_diagnostics(game: dict[str, Any], current_goals: int) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    _collect_bet_nodes(game, nodes)
    target_line = current_goals + 0.5
    near = []
    for n in nodes:
        try:
            p = float(n.get("P"))
        except (TypeError, ValueError):
            continue
        if abs(p - target_line) < 0.001:
            near.append(n)
    return {
        "bet_nodes": len(nodes),
        "target_line": target_line,
        "target_line_nodes": near[:12],
        "sample_nodes": nodes[:12],
    }


def probe_matches(matches: list[Any]) -> dict[str, Any]:
    events, root, err = fetch_live_football()
    result = {"root": root, "error": err, "xbet_live_count": len(events), "matches": []}
    if not events:
        return result
    for m in matches:
        home, away = str(getattr(m, "home", "")), str(getattr(m, "away", ""))
        score_home = int(getattr(m, "home_score", 0) or 0)
        score_away = int(getattr(m, "away_score", 0) or 0)
        row: dict[str, Any] = {
            "home": home, "away": away,
            "minute": int(getattr(m, "minute", 0) or 0),
            "score": f"{score_home}:{score_away}",
        }
        event, similarity, rev = match_event(home, away, events)
        row["similarity"] = round(similarity, 3)
        if not event:
            row["found"] = False
            result["matches"].append(row)
            continue
        row.update({
            "found": True,
            "xbet_id": event.get("I"),
            "xbet_home": event.get("O1") or event.get("O1E"),
            "xbet_away": event.get("O2") or event.get("O2E"),
            "xbet_league": event.get("L") or event.get("LE"),
            "reversed": rev,
        })
        game, game_root, game_err = fetch_game(event.get("I"))
        row["game_root"] = game_root
        row["game_error"] = game_err
        if game:
            row["markets"] = market_diagnostics(game, score_home + score_away)
        result["matches"].append(row)
    return result


def format_probe(result: dict[str, Any]) -> str:
    lines = ["🧪 <b>1xBET LIVE PROBE</b>"]
    if result.get("root"):
        lines.append(f"Feed: <code>{result['root']}</code>")
    lines.append(f"1xBet LIVE football: <b>{result.get('xbet_live_count', 0)}</b>")
    if result.get("error") and not result.get("xbet_live_count"):
        lines.append(f"⚠️ {result['error']}")
    for r in result.get("matches") or []:
        lines.append("")
        lines.append(f"⚽ <b>{r['home']} — {r['away']}</b> | {r['minute']}' {r['score']}")
        if not r.get("found"):
            lines.append(f"❌ не найдено · match {round(float(r.get('similarity',0))*100)}%")
            continue
        lines.append(f"✅ найдено: {r.get('xbet_home')} — {r.get('xbet_away')} · match {round(float(r.get('similarity',0))*100)}%")
        lines.append(f"ID <code>{r.get('xbet_id')}</code> · {r.get('xbet_league') or 'лига —'}")
        markets = r.get("markets") or {}
        lines.append(f"Рыночных selections: <b>{markets.get('bet_nodes',0)}</b> · целевая линия {markets.get('target_line','—')}")
        near = markets.get("target_line_nodes") or []
        if near:
            compact = "; ".join(f"T={x.get('T')} P={x.get('P')} C={x.get('C')} G={x.get('G','-')}" for x in near[:6])
            lines.append(f"🎯 Кандидаты линии: <code>{compact}</code>")
        elif r.get("game_error"):
            lines.append(f"⚠️ GetGameZip: {r['game_error']}")
        else:
            lines.append("ℹ️ целевая линия среди raw selections не найдена")
    return "\n".join(lines)
