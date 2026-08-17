"""Read-only 1xBet/Melbet LiveFeed probe for GOOL shadow testing.

Never changes CORE decisions. It probes modern /service-api/LiveFeed endpoints
first, then legacy /LiveFeed endpoints, matches GOOL/Flashscore live games and
reports detailed market payloads for diagnostics.
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
DEFAULT_ROOTS = (
    "https://1xbet.com/service-api/LiveFeed",
    "https://1xbet.fi/service-api/LiveFeed",
    "https://melbet.com/service-api/LiveFeed",
    "https://1xbet.com/LiveFeed",
    "https://1xbet.fi/LiveFeed",
)
ROOTS = tuple(x.strip().rstrip("/") for x in os.getenv(
    "XBET_LIVE_ROOTS", ",".join(DEFAULT_ROOTS)
).split(",") if x.strip())
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://1xbet.com/",
    "Origin": "https://1xbet.com",
}
TIMEOUT = float(os.getenv("XBET_TIMEOUT", "10"))


def _get(method: str, param_variants: list[dict[str, Any]]) -> tuple[dict[str, Any], str, str | None, list[str]]:
    attempts: list[str] = []
    last_error = None
    for root in ROOTS:
        url = f"{root}/{method}"
        headers = dict(HEADERS)
        if "melbet" in root:
            headers["Referer"] = "https://melbet.com/"
            headers["Origin"] = "https://melbet.com"
        for params in param_variants:
            try:
                r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT, allow_redirects=True)
                attempts.append(f"{root} -> HTTP {r.status_code}")
                if r.status_code != 200:
                    last_error = f"{root}: HTTP {r.status_code}"
                    continue
                try:
                    data = r.json()
                except ValueError:
                    preview = (r.text or "")[:80].replace("\n", " ")
                    last_error = f"{root}: non-JSON {preview!r}"
                    attempts[-1] += " non-JSON"
                    continue
                if isinstance(data, dict) and "Value" in data:
                    attempts[-1] += " JSON/Value"
                    return data, root, None, attempts
                last_error = f"{root}: JSON without Value"
                attempts[-1] += " JSON-no-Value"
            except requests.RequestException as exc:
                msg = f"{root}: {type(exc).__name__}: {exc}"
                attempts.append(msg)
                last_error = msg
    return {}, "", last_error, attempts


def _live_param_variants() -> list[dict[str, Any]]:
    # Legacy public LiveFeed parameters + current service-api style observed on
    # 1xBet-family frontends. Trying both keeps the probe diagnostic/read-only.
    return [
        {
            "sports": 1,
            "count": 1000,
            "lng": "en",
            "mode": 4,
            "country": 1,
            "getEmpty": "true",
        },
        {
            "sports": 1,
            "count": 1000,
            "lng": "en",
            "mode": 4,
            "country": 137,
            "gr": 285,
            "virtualSports": "true",
            "noFilterBlockEvent": "true",
            "getEmpty": "true",
        },
    ]


def fetch_live_football() -> tuple[list[dict[str, Any]], str, str | None, list[str]]:
    data, root, err, attempts = _get("Get1x2_VZip", _live_param_variants())
    value = data.get("Value") if isinstance(data, dict) else None
    return (value if isinstance(value, list) else []), root, err, attempts


def fetch_game(event_id: Any, preferred_root: str | None = None) -> tuple[dict[str, Any], str, str | None, list[str]]:
    roots_before = ROOTS
    try:
        if preferred_root and preferred_root in ROOTS:
            globals()["ROOTS"] = (preferred_root,) + tuple(r for r in ROOTS if r != preferred_root)
        params = [{
            "id": event_id,
            "lng": "en",
            "cfview": 0,
            "isSubGames": "true",
            "GroupEvents": "true",
            "allEventsGroupSubGames": "true",
            "countevents": 250,
            "grMode": 2,
        }]
        data, root, err, attempts = _get("GetGameZip", params)
    finally:
        globals()["ROOTS"] = roots_before
    value = data.get("Value") if isinstance(data, dict) else None
    return (value if isinstance(value, dict) else {}), root, err, attempts


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
    events, root, err, attempts = fetch_live_football()
    result = {"root": root, "error": err, "attempts": attempts, "xbet_live_count": len(events), "matches": []}
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
        game, game_root, game_err, game_attempts = fetch_game(event.get("I"), root)
        row["game_root"] = game_root
        row["game_error"] = game_err
        row["game_attempts"] = game_attempts
        if game:
            row["markets"] = market_diagnostics(game, score_home + score_away)
        result["matches"].append(row)
    return result


def format_probe(result: dict[str, Any]) -> str:
    lines = ["🧪 <b>1xBET/MELBET LIVE PROBE</b>"]
    if result.get("root"):
        lines.append(f"✅ Feed: <code>{result['root']}</code>")
    lines.append(f"LIVE football: <b>{result.get('xbet_live_count', 0)}</b>")
    attempts = result.get("attempts") or []
    if attempts:
        lines.append("\n<b>Endpoint test:</b>")
        lines.extend(f"• <code>{x}</code>" for x in attempts[:12])
    if result.get("error") and not result.get("xbet_live_count"):
        lines.append(f"⚠️ итог: {result['error']}")
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
