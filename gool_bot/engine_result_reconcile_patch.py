"""Keep HT/LATE journal results consistent with the actual Flashscore score.

The engine runtime can temporarily lose an event from the shared LIVE list near FT.
Before/after every engine scan we re-check already created HT/LATE entries against
Flashscore summary.  If the score increased after the entry, the signal is a win
regardless of an earlier transient loss mark.
"""
from __future__ import annotations

import logging

import multi_engine_runtime
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals, update_signal

logger = logging.getLogger("engine_result_reconcile")
_ENGINES = {"first_half", "second_half"}


def reconcile_engine_results() -> int:
    fixed = 0
    for row in all_signals():
        if row.get("kind") != "live" or str(row.get("engine") or "") not in _ENGINES:
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
            fh, fa, _, _ = _score_from_summary(body)
        except Exception as exc:
            logger.info("ENGINE_RECONCILE_SUMMARY_FAILED %s: %s", eid, exc)
            continue
        if (fh + fa) <= (sh + sa):
            continue
        current = str(row.get("result") or "pending").strip().lower()
        if current not in {"+", "win", "won"}:
            if update_signal(
                str(row.get("dedupe_key") or ""),
                result="+",
                final_score=f"{fh}:{fa}",
                reconciled_from_summary=True,
            ):
                fixed += 1
                logger.warning(
                    "ENGINE_RESULT_RECONCILED %s %s - %s %s -> %s:%s",
                    row.get("engine"),
                    row.get("home"),
                    row.get("away"),
                    row.get("score_at_signal"),
                    fh,
                    fa,
                )
    return fixed


_original_scan_engines = multi_engine_runtime.scan_engines


def _scan_engines_with_reconcile(live):
    reconcile_engine_results()
    result = _original_scan_engines(live)
    reconcile_engine_results()
    return result


multi_engine_runtime.scan_engines = _scan_engines_with_reconcile
