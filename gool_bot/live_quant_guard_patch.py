"""Final LIVE-only gate before CORE Telegram delivery."""
from __future__ import annotations
import logging
import live_candidate_patch as lc
from signal_journal import all_signals
from risk_controller import can_open,value_ok
logger=logging.getLogger("live_quant_guard")
_original_send=lc._send


def _entry_reason(text:str)->str|None:
    t=text or ""
    if "НОВЫЙ ВХОД ПОСЛЕ ГОЛА" in t:return "reentry"
    if "МОЖНО ЗАХОДИТЬ" in t or "МОЖНО РАССМАТРИВАТЬ ВХОД" in t:return "signal"
    return None


def _best_primary(recs):
    rows=[r for r in list(recs or []) if isinstance(r,dict)]
    row=next((r for r in rows if r.get("best_bet")),None)
    if row is None and rows:row=max(rows,key=lambda r:float(r.get("value_edge",-999) or -999))
    if row is None:return None
    try:
        return {"market":"TOTAL_OVER","scope":str(row["scope"]),"line":float(row["line"]),"odd":float(row["odd"]),"source":str(row.get("source") or "LIVE"),"bookmakers":int(row.get("bookmakers",0) or 0),"confidence":row.get("confidence"),"value_edge":row.get("value_edge")}
    except (KeyError,TypeError,ValueError):return None


def _send(match,pressure,recs,text):
    reason=_entry_reason(text)
    if not reason:return _original_send(match,pressure,recs,text)
    eid=str(getattr(match,"event_id","") or "");rows=all_signals();allowed,why=can_open(rows,eid)
    if not allowed:
        logger.info("CORE_EXPOSURE_REJECT %s %s",eid,why);return False
    primary=_best_primary(recs);ok,why=value_ok(primary,reason)
    if not ok:
        logger.info("CORE_VALUE_REJECT %s %s",eid,why);return False
    return _original_send(match,pressure,recs,text)

lc._send=_send
logger.info("LIVE quant guard enabled: auditable primary + positive edge + shared exposure cap")
