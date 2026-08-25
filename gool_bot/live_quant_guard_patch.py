"""Final exposure/cadence gate before CORE Telegram delivery.

Analytics decides signal quality. This guard enforces only match-level cadence:
max two entries, one open entry, cooldown, and no new signal after 75'. Odds do
not participate.
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
 eid=str(getattr(match,"event_id","") or "");minute=int(getattr(match,"minute",0) or 0)
 allowed,why=can_open(all_signals(),eid,current_minute=minute)
 if not allowed:
  logger.info("CORE_CADENCE_REJECT %s %d' %s",eid,minute,why)
  return False
 return _original_send(match,pressure,recs,text)

lc._send=_send
logger.info("LIVE quant guard: max2 + cooldown + <=75m; odds cannot block CORE signals")
