"""Settle GOOL CORE journal v4 by the stored primary market, not by 'next goal'."""
from __future__ import annotations
import logging,time
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals,update_signal
from market_settlement import fully_won_now,settle_primary
logger=logging.getLogger("core_primary_reconcile")


def reconcile(live)->int:
    live_by={str(m.event_id):m for m in live};now=time.time();fixed=0
    for row in all_signals():
        if row.get("kind")!="live" or str(row.get("reason") or "") not in {"signal","reentry"}:continue
        if int(row.get("journal_version",0) or 0)<4 or str(row.get("result") or "pending").strip().lower()!="pending":continue
        primary=row.get("primary")
        if not isinstance(primary,dict):continue
        eid=str(row.get("event_id") or "");m=live_by.get(eid)
        if m:
            score=f"{int(m.home_score)}:{int(m.away_score)}"
            if not fully_won_now(primary,score):continue
            settlement=settle_primary(primary,score)
            if settlement and update_signal(str(row.get("dedupe_key") or ""),**settlement,final_score=score,settled_ts=int(now),result_source="primary_market_crossed"):
                fixed+=1;logger.info("CORE_PRIMARY_EARLY_WIN %s %s",eid,score)
            continue
        age=now-float(row.get("created_ts",0) or 0)
        if age<12*60:continue
        try:
            body=fetch_summary(eid)
            if not body:continue
            fh,fa,_,_=_score_from_summary(body);score=f"{fh}:{fa}"
        except Exception as exc:
            logger.info("CORE_PRIMARY_SUMMARY_FAILED %s: %s",eid,exc);continue
        settlement=settle_primary(primary,score)
        if settlement and update_signal(str(row.get("dedupe_key") or ""),**settlement,final_score=score,settled_ts=int(now),result_source="primary_market_final"):
            fixed+=1;logger.info("CORE_PRIMARY_SETTLED %s %s result=%s pnl=%s",eid,score,settlement.get("result"),settlement.get("pnl_units"))
    return fixed
