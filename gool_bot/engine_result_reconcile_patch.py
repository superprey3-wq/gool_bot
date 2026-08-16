"""Keep HT/LATE journal results consistent with Flashscore and notify outcomes.

HT HUNTER is settled only from the first-half score. LATE RISK uses the
second-half/full score. When a still-pending signal is settled by summary
reconciliation, send the same blue/red result card as the live runtime.
"""
from __future__ import annotations

import logging
import re
from types import SimpleNamespace

import multi_engine_runtime
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals, update_signal

logger = logging.getLogger("engine_result_reconcile")
_ENGINES = {"first_half", "second_half"}


def _has_reached_second_half(body: str) -> bool:
    for chunk in (body or "").split("~III"):
        mm = re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})", chunk)
        if mm:
            try:
                if int(mm.group(1)) > 45:
                    return True
            except Exception:
                pass
    return False


def _result_match(row, score, minute):
    try:
        hs, as_ = map(int, str(score or row.get("score_at_signal") or "0:0").split(":"))
    except Exception:
        hs, as_ = 0, 0
    return SimpleNamespace(
        event_id=str(row.get("event_id") or ""),
        home=str(row.get("home") or ""),
        away=str(row.get("away") or ""),
        league=str(row.get("league") or ""),
        home_score=hs,
        away_score=as_,
        minute=int(minute or row.get("minute") or 0),
        is_halftime=False,
    )


def _notify_pending_settlement(row, engine, result, score, minute):
    """Only notify real pending->result transitions; never replay historical fixes."""
    try:
        match = _result_match(row, score, minute)
        multi_engine_runtime._send_all(
            match,
            engine,
            float(row.get("risk_score", 0) or 0),
            row.get("trend_delta") or {},
            row.get("odd"),
            result,
        )
        logger.info("ENGINE_RECONCILE_RESULT_CARD %s %s %s", engine, result, row.get("event_id"))
    except Exception:
        logger.exception("ENGINE_RECONCILE_RESULT_CARD_FAILED %s %s", engine, row.get("event_id"))


def reconcile_engine_results() -> int:
    fixed = 0
    for row in all_signals():
        engine = str(row.get("engine") or "")
        if row.get("kind") != "live" or engine not in _ENGINES:
            continue
        try:
            sh, sa = map(int, str(row.get("score_at_signal", "0:0")).split(":"))
        except Exception:
            continue
        eid = str(row.get("event_id") or "")
        if not eid:
            continue
        try:
            body = fetch_summary(eid)
            if not body:
                continue
            fh, fa, hh, ha = _score_from_summary(body)
        except Exception as exc:
            logger.info("ENGINE_RECONCILE_SUMMARY_FAILED %s: %s", eid, exc)
            continue

        current = str(row.get("result") or "pending").strip().lower()
        was_pending = current == "pending"

        if engine == "first_half":
            ht_goal_after_signal = (hh + ha) > (sh + sa)
            if ht_goal_after_signal:
                target = "+"
                result_name = "win"
                final_score = f"{hh}:{ha}"
                result_minute = 45
            elif _has_reached_second_half(body):
                target = "-"
                result_name = "loss"
                final_score = f"{hh}:{ha}"
                result_minute = 45
            else:
                continue

            if current != target:
                if update_signal(
                    str(row.get("dedupe_key") or ""),
                    result=target,
                    final_score=final_score,
                    reconciled_from_summary=True,
                    reconciled_market="first_half",
                ):
                    fixed += 1
                    if was_pending:
                        _notify_pending_settlement(row, engine, result_name, final_score, result_minute)
                    logger.warning(
                        "ENGINE_RESULT_RECONCILED first_half %s - %s %s -> HT %s (%s)",
                        row.get("home"), row.get("away"), row.get("score_at_signal"), final_score, target,
                    )
            continue

        # LATE RISK win: any later second-half goal after the entry.
        if (fh + fa) <= (sh + sa):
            continue
        if current not in {"+", "win", "won"}:
            final_score = f"{fh}:{fa}"
            if update_signal(
                str(row.get("dedupe_key") or ""),
                result="+",
                final_score=final_score,
                reconciled_from_summary=True,
                reconciled_market="second_half",
            ):
                fixed += 1
                if was_pending:
                    _notify_pending_settlement(row, engine, "win", final_score, 90)
                logger.warning(
                    "ENGINE_RESULT_RECONCILED second_half %s - %s %s -> %s",
                    row.get("home"), row.get("away"), row.get("score_at_signal"), final_score,
                )
    return fixed


_original_scan_engines = multi_engine_runtime.scan_engines


def _scan_engines_with_reconcile(live):
    reconcile_engine_results()
    result = _original_scan_engines(live)
    reconcile_engine_results()
    return result


multi_engine_runtime.scan_engines = _scan_engines_with_reconcile
