"""Experimental owner-only market anomaly signal.

This engine is intentionally independent from CORE/1T/2T. It observes the remote
Progruz market node and sends a TEXT-ONLY Telegram message only when several
market-anomaly features agree. It never changes GOOL eligibility/probability.

The feed shows repricing/suspension patterns, not actual bookmaker cash volume,
so messages are labelled TEST rather than claiming known money flow.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import market_node_bridge
import telegram_subscribers

log = logging.getLogger("market_test_signal")

COOLDOWN = max(300, int(os.getenv("MARKET_TEST_COOLDOWN_SECONDS", "1800")))
LOOKBACK = max(120, int(os.getenv("MARKET_TEST_LOOKBACK_SECONDS", "600")))
MIN_SCORE = max(2, int(os.getenv("MARKET_TEST_MIN_SCORE", "3")))
_LOCK = threading.Lock()
_LAST_SENT: dict[str, float] = {}
_LAST_FINGERPRINT: dict[str, str] = {}


def _journal_path() -> Path:
    explicit = os.getenv("MARKET_TEST_JOURNAL", "").strip()
    if explicit:
        return Path(explicit)
    runtime = os.getenv("RUNTIME_DATA_DIR", "").strip()
    if runtime:
        return Path(runtime) / "market_test_signals.jsonl"
    data = Path("/data")
    if data.exists() and os.access(str(data), os.W_OK):
        return data / "market_test_signals.jsonl"
    return Path("market_test_signals.jsonl")


def _recent_points(row: dict, now: float) -> list[list[float]]:
    pts = []
    for raw in row.get("points") or []:
        try:
            ts = float(raw[0]); odd = float(raw[1]); line = None if raw[2] is None else float(raw[2])
        except Exception:
            continue
        if odd <= 1.0 or ts < now - LOOKBACK:
            continue
        pts.append([ts, odd, line])
    return sorted(pts, key=lambda x: x[0])


def _evaluate(key: str, row: dict, now: float) -> dict | None:
    pts = _recent_points(row, now)
    if len(pts) < 2:
        return None
    first, last = pts[0], pts[-1]
    elapsed = max(1.0, last[0] - first[0])
    delta_pp = (1.0 / last[1] - 1.0 / first[1]) * 100.0
    line_move = 0.0
    if first[2] is not None and last[2] is not None:
        line_move = last[2] - first[2]
    pressure = delta_pp + max(-2.0, min(2.0, line_move * 2.0))

    suspends = int(row.get("suspends", 0) or 0)
    reopens = int(row.get("reopens", 0) or 0)
    reopen_delta = float(row.get("last_reopen_delta_pp", 0) or 0)

    score = 0
    reasons = []
    if abs(pressure) >= 4.5:
        score += 2; reasons.append("strong_reprice")
    elif abs(pressure) >= 3.0:
        score += 1; reasons.append("reprice")
    if abs(pressure) >= 3.0 and elapsed <= 180:
        score += 1; reasons.append("fast_move")
    if suspends >= 1 and reopens >= 1:
        score += 1; reasons.append("suspend_reopen")
    if suspends >= 2:
        score += 1; reasons.append("repeated_suspend")
    if abs(reopen_delta) >= 1.5:
        score += 1; reasons.append("reopen_reprice")
    if abs(line_move) >= 0.25:
        score += 1; reasons.append("line_shift")

    # Require an actual directional move or a verified suspend->reopen repricing.
    if score < MIN_SCORE or (abs(pressure) < 3.0 and abs(reopen_delta) < 1.5):
        return None

    direction_value = pressure if abs(pressure) >= 1.0 else reopen_delta
    direction = "OVER" if direction_value > 0 else "UNDER"
    fingerprint = f"{direction}:{round(last[2] or 0,2)}:{suspends}:{round(pressure,1)}"
    return {
        "key": key,
        "home": row.get("home") or "?",
        "away": row.get("away") or "?",
        "event_id": row.get("event_id"),
        "direction": direction,
        "score": score,
        "reasons": reasons,
        "delta_pp": round(delta_pp, 2),
        "pressure_pp": round(pressure, 2),
        "elapsed": int(elapsed),
        "start_odds": round(first[1], 3),
        "last_odds": round(last[1], 3),
        "start_line": first[2],
        "last_line": last[2],
        "line_move": round(line_move, 2),
        "suspends": suspends,
        "reopens": reopens,
        "reopen_delta_pp": round(reopen_delta, 2),
        "fingerprint": fingerprint,
        "created_ts": now,
    }


def _message(sig: dict) -> str:
    arrow = "⬆️" if sig["direction"] == "OVER" else "⬇️"
    side = "ТБ" if sig["direction"] == "OVER" else "ТМ"
    line = sig.get("last_line")
    line_txt = f" {line:g}" if isinstance(line, (int, float)) else ""
    level = "EXTREME" if sig["score"] >= 5 else "STRONG"
    parts = [
        "🧪 <b>ТЕСТ · ПРОГРУЗ</b>",
        f"⚽ <b>{sig['home']} — {sig['away']}</b>",
        f"{arrow} Направление: <b>{side}{line_txt}</b>",
        f"Кэф: <b>{sig['start_odds']} → {sig['last_odds']}</b> · давление {sig['pressure_pp']:+.2f} п.п. · {sig['elapsed']} сек",
    ]
    if sig.get("start_line") is not None and sig.get("last_line") is not None and sig["start_line"] != sig["last_line"]:
        parts.append(f"Линия: <b>{sig['start_line']:g} → {sig['last_line']:g}</b>")
    if sig["suspends"] or sig["reopens"]:
        parts.append(f"Блокировки: <b>{sig['suspends']}</b> · reopen: <b>{sig['reopens']}</b> · repricing {sig['reopen_delta_pp']:+.2f} п.п.")
    parts += [
        f"Уровень: <b>{level} · {sig['score']}</b>",
        "<i>Экспериментальный рыночный сигнал. Не влияет на CORE / 1T / 2T.</i>",
    ]
    return "\n".join(parts)


def _write_journal(sig: dict, delivered: bool) -> None:
    record = dict(sig); record["delivered"] = bool(delivered); record["kind"] = "market_test"
    try:
        p = _journal_path(); p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as exc:
        log.warning("MARKET_TEST journal failed: %s", exc)


def scan_once() -> int:
    """Evaluate latest remote snapshot and send owner-only TEST anomalies."""
    now = time.time()
    with market_node_bridge.LOCK:
        rows = {k: dict(v) for k, v in market_node_bridge.REMOTE.items()}
    if not rows:
        return 0

    owner = telegram_subscribers._owner_chat_id()
    if not owner:
        log.warning("MARKET_TEST skipped: TELEGRAM_CHAT_ID is empty")
        return 0

    sent = 0
    for key, row in rows.items():
        sig = _evaluate(key, row, now)
        if not sig:
            continue
        with _LOCK:
            last_ts = _LAST_SENT.get(key, 0.0)
            last_fp = _LAST_FINGERPRINT.get(key)
            if now - last_ts < COOLDOWN and last_fp == sig["fingerprint"]:
                continue
            _LAST_SENT[key] = now
            _LAST_FINGERPRINT[key] = sig["fingerprint"]
        delivered = telegram_subscribers._post_message(owner, _message(sig))
        _write_journal(sig, delivered)
        if delivered:
            sent += 1
            log.info("MARKET_TEST_SENT key=%s dir=%s score=%d pressure=%+.2f", key, sig["direction"], sig["score"], sig["pressure_pp"])
        else:
            log.warning("MARKET_TEST_DELIVERY_FAIL key=%s", key)
    return sent
