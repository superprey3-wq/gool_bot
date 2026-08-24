"""Settle HT/LATE journal rows from the actual stored primary market."""
from __future__ import annotations
import logging,re,time
from types import SimpleNamespace
import multi_engine_runtime
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_journal import all_signals,update_signal
from market_settlement import settle_primary
logger=logging.getLogger("engine_result_reconcile");_ENGINES={"first_half","second_half"}

def _has_reached_second_half(body:str)->bool:
    for chunk in (body or "").split("~III"):
        mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})",chunk)
        if mm:
            try:
                if int(mm.group(1))>45:return True
            except:pass
    return False

def _result_match(row,score,minute):
    try:hs,as_=map(int,str(score or row.get("score_at_signal") or "0:0").split(":"))
    except:hs=as_=0
    return SimpleNamespace(event_id=str(row.get("event_id") or ""),home=str(row.get("home") or ""),away=str(row.get("away") or ""),league=str(row.get("league") or ""),home_score=hs,away_score=as_,minute=int(minute or row.get("minute") or 0),is_halftime=False)

def _notify(row,engine,result,score,minute):
    if result not in {"+","-"}:return
    try:multi_engine_runtime._send_all(_result_match(row,score,minute),engine,float(row.get("risk_score",0) or 0),row.get("trend_delta") or {},row.get("odd"),"win" if result=="+" else "loss")
    except Exception:logger.exception("ENGINE_RESULT_CARD_FAILED %s %s",engine,row.get("event_id"))

def _apply(row,score,scope,minute):
    settlement=settle_primary(row.get("primary"),score)
    if not settlement:return False
    fields=dict(settlement);fields.update(final_score=score,settled_ts=int(time.time()),result_source="primary_market_settlement",reconciled_from_summary=True,reconciled_market=scope)
    ok=update_signal(str(row.get("dedupe_key") or ""),**fields)
    if ok:_notify(row,str(row.get("engine") or ""),str(settlement.get("result")),score,minute)
    return ok

def reconcile_engine_results(live_ids:set[str]|None=None)->int:
    fixed=0;now=time.time();live_ids=live_ids or set()
    for row in all_signals():
        engine=str(row.get("engine") or "")
        if row.get("kind")!="live" or engine not in _ENGINES or str(row.get("result") or "pending").strip().lower()!="pending":continue
        # New journal rows must have an auditable primary. Old history is left untouched.
        if int(row.get("journal_version",0) or 0)<4 or not isinstance(row.get("primary"),dict):continue
        eid=str(row.get("event_id") or "")
        if not eid:continue
        try:
            body=fetch_summary(eid)
            if not body:continue
            fh,fa,hh,ha=_score_from_summary(body)
        except Exception as exc:
            logger.info("ENGINE_RECONCILE_SUMMARY_FAILED %s: %s",eid,exc);continue
        if engine=="first_half":
            if not _has_reached_second_half(body):continue
            if _apply(row,f"{hh}:{ha}","first_half",45):fixed+=1
            continue
        # LATE is a full-time total. Do not settle a transiently missing LIVE row too early.
        age=now-float(row.get("created_ts",0) or 0)
        if eid in live_ids or age<8*60:continue
        if _apply(row,f"{fh}:{fa}","full_time",90):fixed+=1
    return fixed

_original_scan_engines=multi_engine_runtime.scan_engines
def _scan_engines_with_reconcile(live):
    ids={str(m.event_id) for m in live};reconcile_engine_results(ids);result=_original_scan_engines(live);reconcile_engine_results(ids);return result
multi_engine_runtime.scan_engines=_scan_engines_with_reconcile
