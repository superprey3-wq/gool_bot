"""Final CORE entry market freshness gate.

Right before Telegram delivery, reconcile the current match state and rebuild the
selected market from current LSApp/Bovada/Kambi quotes. This prevents a card from
showing a line/price calculated for an older score or minute. The caller's recs
list is replaced in-place so the journal records the same refreshed primary.
"""
from __future__ import annotations
import logging
import live_candidate_patch as lc
import unified_bot
import telegram_image_signal_patch as tip
logger=logging.getLogger("entry_market_refresh")
_orig_send=lc._send

def _is_entry(text):
 t=str(text or "")
 return "МОЖНО ЗАХОДИТЬ" in t or "МОЖНО РАССМАТРИВАТЬ ВХОД" in t or "НОВЫЙ ВХОД ПОСЛЕ ГОЛА" in t

def _best(rows):
 return next((r for r in (rows or []) if isinstance(r,dict) and r.get("best_concrete_bet")),None) or next((r for r in (rows or []) if isinstance(r,dict) and r.get("best_bet")),None)

def _send(match,pressure,recs,text):
 if not _is_entry(text):return _orig_send(match,pressure,recs,text)
 synced=tip._sync_entry_match(match) or match
 old=_best(recs)
 try:
  entries=unified_bot._fetch_event_odds(str(getattr(synced,"event_id","") or ""))
  fresh_recs,fresh_market=lc._market(entries,synced,pressure)
 except Exception as exc:
  logger.info("ENTRY_MARKET_REFRESH_FAILED %s %s",getattr(match,"event_id","?"),exc);return False
 fresh=_best(fresh_recs)
 if fresh is None:
  logger.info("ENTRY_MARKET_REFRESH_REJECT %s no refreshed primary",getattr(match,"event_id","?"));return False
 try:
  old_sig=(str((old or {}).get("market_type")),(old or {}).get("line"),float((old or {}).get("odd",0) or 0),str((old or {}).get("source")))
  new_sig=(str(fresh.get("market_type")),fresh.get("line"),float(fresh.get("odd",0) or 0),str(fresh.get("source")))
 except Exception:old_sig,new_sig=(None,),(None,)
 logger.info("ENTRY_MARKET_REFRESH event=%s minute=%s score=%s:%s old=%s new=%s sources=%s spread=%s",getattr(synced,"event_id","?"),getattr(synced,"minute","?"),getattr(synced,"home_score","?"),getattr(synced,"away_score","?"),old_sig,new_sig,[(x.get('source'),x.get('odd')) for x in (fresh.get('source_prices') or [])],fresh.get('source_spread_pct'))
 if isinstance(recs,list):recs[:]=fresh_recs
 return _orig_send(synced,pressure,recs,text)

lc._send=_send
logger.info("CORE entry market refresh active")
