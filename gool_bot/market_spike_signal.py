"""Owner-only automatic alert for unusually sharp LIVE market moves.

Uses the secondary market node /anomalies feed (already Flashscore live-gated).
It is independent from GOOL CORE signals and sends only genuinely new sharp
market fingerprints after the process baseline has been established.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

import market_node_bridge as bridge
import telegram_subscribers as tg

log = logging.getLogger("market_spike_signal")
_LOCK = threading.Lock()
_PRIMED = False
_SEEN: dict[str, str] = {}
_LAST_SENT: dict[str, float] = {}


def _fetch():
    if not bridge.URL:
        return []
    headers = {"Authorization": "Bearer " + bridge.SECRET} if bridge.SECRET else {}
    try:
        r = requests.get(bridge.URL + "/anomalies", headers=headers, timeout=10)
        if r.status_code == 401:
            raise RuntimeError("401 unauthorized")
        r.raise_for_status()
        body = r.json() or {}
        rows = body.get("signals") or body.get("anomalies") or []
        return [x for x in rows if isinstance(x, dict)]
    except Exception as exc:
        log.warning("MARKET_SPIKE_PULL_FAIL %s: %s", type(exc).__name__, exc)
        return []


def _sharp(sig: dict) -> bool:
    """Require a move strong enough to deserve an immediate push."""
    try:
        delta = abs(float(sig.get("delta_pp", 0) or 0))
        elapsed = max(1, int(sig.get("elapsed", 0) or 0))
        score = int(sig.get("score", 0) or 0)
        reopen = abs(float(sig.get("reopen_delta_pp", 0) or 0))
        line_move = abs(float(sig.get("line_move", 0) or 0))
    except Exception:
        return False

    # Very large repricing; or a fast meaningful move; or a multi-factor anomaly.
    if delta >= 8:
        return True
    if delta >= 5 and elapsed <= 180:
        return True
    if score >= 5 and (delta >= 4 or reopen >= 2 or line_move >= 0.5):
        return True
    return False


def _id(sig: dict) -> str:
    return f"{sig.get('key')}:{sig.get('market_key')}"


def _tournament(sig: dict) -> str:
    try:
        d = bridge.diagnostic_for_match(sig.get("home"), sig.get("away")) or {}
    except Exception:
        d = {}
    league = str(d.get("league") or d.get("tournament") or "").strip()
    country = str(d.get("country") or "").strip()
    if league and country and country.casefold() not in league.casefold():
        return f"{country} · {league}"
    return league


def _message(sig: dict) -> str:
    delta = float(sig.get("delta_pp", 0) or 0)
    elapsed = int(sig.get("elapsed", 0) or 0)
    market = str(sig.get("market") or "рынок")
    old = sig.get("start_odds")
    new = sig.get("last_odds")
    try:
        odds = f"{float(old):.2f} → {float(new):.2f}"
    except Exception:
        odds = "—"
    direction = "вероятность резко выросла" if delta > 0 else "вероятность резко упала"
    tournament = _tournament(sig)
    lines = [
        "🚨 <b>ПРОГРУЗ РЫНКА</b>",
        f"⚽ <b>{sig.get('home') or '?'} — {sig.get('away') or '?'}</b>",
    ]
    if tournament:
        lines.append(f"🏆 {tournament}")
    lines.extend([
        f"📊 <b>{market}</b>",
        f"Кэф: <b>{odds}</b>",
        f"Движение: <b>{delta:+.2f} п.п.</b> за {elapsed} сек · {direction}",
    ])
    a, b = sig.get("start_line"), sig.get("last_line")
    if a is not None and b is not None and a != b:
        lines.append(f"Линия: <b>{a} → {b}</b>")
    susp = int(sig.get("suspends", 0) or 0)
    reop = int(sig.get("reopens", 0) or 0)
    if susp or reop:
        lines.append(f"Блокировки: {susp} · reopen: {reop}")
    lines.append("<i>Автосигнал: рынок среагировал резко. Только для владельца.</i>")
    return "\n".join(lines)


def scan_once() -> int:
    global _PRIMED
    rows = _fetch()
    if not rows:
        return 0
    owner = tg._owner_chat_id()
    if not owner:
        return 0
    now = time.time()

    with _LOCK:
        if not _PRIMED:
            for sig in rows:
                _SEEN[_id(sig)] = str(sig.get("fingerprint") or "")
            _PRIMED = True
            log.info("MARKET_SPIKE_BASELINE candidates=%d sent=0", len(rows))
            return 0

    sent = 0
    for sig in rows:
        key = _id(sig)
        fp = str(sig.get("fingerprint") or "")
        with _LOCK:
            prev = _SEEN.get(key)
            if prev == fp:
                continue
            _SEEN[key] = fp
            if not _sharp(sig):
                continue
            if now - _LAST_SENT.get(key, 0) < 300:
                continue
            _LAST_SENT[key] = now
        if tg._post_message(owner, _message(sig)):
            sent += 1
            log.info("MARKET_SPIKE_SENT key=%s market=%s delta=%+.2f", key, sig.get("market"), float(sig.get("delta_pp", 0) or 0))
        else:
            log.warning("MARKET_SPIKE_DELIVERY_FAIL key=%s", key)
    return sent
