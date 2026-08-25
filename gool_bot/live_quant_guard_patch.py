"""Final LIVE-only exposure gate before CORE Telegram delivery.

Odds/edge are intentionally NOT used here. A signal is allowed or rejected by
analytics upstream; this guard only prevents duplicate/open exposure spam.
"""
from __future__ import annotations
import logging
import live_candidate_patch as lc
from signal_journal import all_signals
from risk_controller import can_open
logger=logging.getLogger("live_quant_guard");_original_send=lc._send

def _entry_reason(text):
 t=text or ""
 if "НОВЫЙ ВХОД ПОСЛЕ ГОЛА" in t:return "reentry"
 if "МОЖНО ЗАХОДИТЬ" in t or "МОЖНО РАССМАТРИВАТЬ ВХОД" in t:return "signal"
 return None

def _send(match,pressure,recs,text):
 reason=_entry_reason(text)
 if not reason:return _original_send(match,pressure,recs,text)
 eid=str(getattr(match,"event_id","") or "");allowed,why=can_open(all_signals(),eid)
 if not allowed:logger.info("CORE_EXPOSURE_REJECT %s %s",eid,why);return False
 return _original_send(match,pressure,recs,text)

lc._send=_send
logger.info("LIVE quant guard: exposure-only; odds cannot block CORE signals")
