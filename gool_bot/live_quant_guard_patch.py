"""Final LIVE-only gate before CORE Telegram delivery."""
from __future__ import annotations
import logging
import live_candidate_patch as lc
from signal_journal import all_signals
from risk_controller import can_open,value_ok
logger=logging.getLogger("live_quant_guard");_original_send=lc._send

def _entry_reason(text):
 t=text or ""
 if "НОВЫЙ ВХОД ПОСЛЕ ГОЛА" in t:return "reentry"
 if "МОЖНО ЗАХОДИТЬ" in t or "МОЖНО РАССМАТРИВАТЬ ВХОД" in t:return "signal"
 return None
def _best_primary(recs):
 rows=[r for r in list(recs or []) if isinstance(r,dict)];row=next((r for r in rows if r.get("best_concrete_bet")),None) or next((r for r in rows if r.get("best_bet")),None)
 if row is None:return None
 try:
  odd=float(row["odd"]);kind=str(row.get("market_type") or "TOTAL_OVER");primary={"market":kind,"market_type":kind,"scope":str(row.get("scope") or "FULL_TIME"),"odd":odd,"source":str(row.get("source") or "LIVE"),"bookmakers":int(row.get("source_count") or row.get("bookmakers") or 1),"confidence":row.get("selector_confidence",row.get("confidence")),"value_edge":row.get("selector_edge",row.get("value_edge")),"market_status":row.get("external_market_status") or row.get("market_status")}
  if row.get("line") is not None:primary["line"]=float(row["line"])
  if row.get("team_side"):primary["team_side"]=row.get("team_side");primary["team_name"]=row.get("team_name")
  return primary
 except (KeyError,TypeError,ValueError):return None
def _send(match,pressure,recs,text):
 reason=_entry_reason(text)
 if not reason:return _original_send(match,pressure,recs,text)
 eid=str(getattr(match,"event_id","") or "");allowed,why=can_open(all_signals(),eid)
 if not allowed:logger.info("CORE_EXPOSURE_REJECT %s %s",eid,why);return False
 primary=_best_primary(recs);ok,why=value_ok(primary,reason)
 if not ok:logger.info("CORE_VALUE_REJECT %s %s",eid,why);return False
 return _original_send(match,pressure,recs,text)
lc._send=_send
logger.info("LIVE quant guard enabled for selected multi-market primary")
