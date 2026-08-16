"""Keep HT/LATE journal results consistent with the actual Flashscore score.

HT HUNTER must be settled only from the FIRST-HALF score.  A goal scored in the
second half must never turn an already lost HT signal into a win.

LATE RISK still uses the full/current score because its signal belongs to the
second half.
"""
from __future__ import annotations

import logging
import re

import multi_engine_runtime
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals, update_signal

logger = logging.getLogger("engine_result_reconcile")
_ENGINES = {"first_half", "second_half"}


def _has_reached_second_half(body: str) -> bool:
    """True once Flashscore summary contains any event after minute 45."""
    for chunk in (body or "").split("~III"):
        mm = re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})", chunk)
        if mm:
            try:
                if int(mm.group(1)) > 45:
                    return True
            except Exception:
                pass
    return False


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

        if engine == "first_half":
            # Critical rule: compare the signal score with the HALF-TIME score,
            # never with the full-time/current score.
            ht_goal_after_signal = (hh + ha) > (sh + sa)
            if ht_goal_after_signal:
                target = "+"
                final_score = f"{hh}:{ha}"
            elif _has_reached_second_half(body):
                # Once 2H has started, the HT market is definitively lost if no
                # first-half goal occurred after the signal. This also repairs
                # historical false wins produced by the old reconciliation code.
                target = "-"
                final_score = f"{hh}:{ha}"
            else:
                # First half is still live and no goal has happened yet.
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
                    logger.warning(
                        "ENGINE_RESULT_RECONCILED first_half %s - %s %s -> HT %s (%s)",
                        row.get("home"),
                        row.get("away"),
                        row.get("score_at_signal"),
                        final_score,
                        target,
                    )
            continue

        # LATE RISK: a later goal in the second half is the intended outcome.
        if (fh + fa) <= (sh + sa):
            continue
        if current not in {"+", "win", "won"}:
            if update_signal(
                str(row.get("dedupe_key") or ""),
                result="+",
                final_score=f"{fh}:{fa}",
                reconciled_from_summary=True,
                reconciled_market="second_half",
            ):
                fixed += 1
                logger.warning(
                    "ENGINE_RESULT_RECONCILED second_half %s - %s %s -> %s:%s",
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
