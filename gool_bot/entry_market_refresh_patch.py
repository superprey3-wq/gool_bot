"""Final CORE entry LIVE-odds freshness gate.

Statistics/model quality remains the primary signal. Odds are optional enrichment:
we only attach/use them when a fresh in-play quote is rebuilt immediately before
Telegram delivery. Missing/stale odds never invent a price and never downgrade the
sporting analysis; the card can be sent as an ANALYTICS signal without odds.
"""
from __future__ import annotations
import logging,time
import live_candidate_patch as lc
import unified_bot
import telegram_image_signal_patch as tip
logger=logging.getLogger("entry_market_refresh")
_orig_send=lc._send
MAX_QUOTE_AGE=20.0

def _is_entry(text):
 t=str(text or "")
 return "МОЖНО ЗАХОДИТЬ" in t or "МОЖНО РАССМАТРИВАТЬ ВХОД" in t or "НОВЫЙ ВХОД ПОСЛЕ ГОЛА" in t

def _best(rows):
 return next((r for r in (rows or []) if isinstance(r,dict) and r.get("best_concrete_bet")),None) or next((r for r in (rows or []) if isinstance(r,dict) and r.get("best_bet")),None)

def _fresh(row):
 if not isinstance(row,dict):return False
 try:age=time.time()-float(row.get("quote_ts") or 0)
 except Exception:return False
 # A quote must be created by the current LIVE refresh and have a usable price.
 try:odd=float(row.get("odd") or 0)
 except Exception:return False
 return 0<=age<=MAX_QUOTE_AGE and odd>1.001

def _strip_odds(rows):
 """Keep the analytical signal, but remove unverified/stale betting prices."""
 out=[]
 for r in rows or []:
  if not isinstance(r,dict):continue
  x=dict(r)
  for k in ("odd","source","source_prices","source_count","source_spread_pct","market_consensus","market_status","external_market_status","value_edge","quote_ts","best_bet","best_concrete_bet"):
   x.pop(k,None)
  x["live_odds_status"]="UNAVAILABLE"
  out.append(x)
 return out

def _send(match,pressure,recs,text):
 if not _is_entry(text):return _orig_send(match,pressure,recs,text)
 synced=tip._sync_entry_match(match) or match
 old=_best(recs)
 try:
  entries=unified_bot._fetch_event_odds(str(getattr(synced,"event_id","") or ""))
  fresh_recs,fresh_market=lc._market(entries,synced,pressure)
 except Exception as exc:
  logger.info("ENTRY_LIVE_ODDS_UNAVAILABLE event=%s reason=refresh_failed err=%s",getattr(match,"event_id","?"),exc)
  clean=_strip_odds(recs)
  if isinstance(recs,list):recs[:]=clean
  return _orig_send(synced,pressure,recs,text)
 fresh=_best(fresh_recs)
 if fresh is None or not _fresh(fresh):
  logger.info("ENTRY_LIVE_ODDS_UNAVAILABLE event=%s minute=%s score=%s:%s reason=%s",getattr(synced,"event_id","?"),getattr(synced,"minute","?"),getattr(synced,"home_score","?"),getattr(synced,"away_score","?"),"no_market" if fresh is None else "stale_quote")
  clean=_strip_odds(fresh_recs or recs)
  if isinstance(recs,list):recs[:]=clean
  return _orig_send(synced,pressure,recs,text)
 try:
  old_sig=(str((old or {}).get("market_type")),(old or {}).get("line"),float((old or {}).get("odd",0) or 0),str((old or {}).get("source")))
  new_sig=(str(fresh.get("market_type")),fresh.get("line"),float(fresh.get("odd",0) or 0),str(fresh.get("source")))
  age=round(time.time()-float(fresh.get("quote_ts") or 0),1)
 except Exception:old_sig,new_sig,age=(None,),(None,),None
 logger.info("ENTRY_LIVE_ODDS_OK event=%s minute=%s score=%s:%s age=%ss old=%s new=%s sources=%s spread=%s",getattr(synced,"event_id","?"),getattr(synced,"minute","?"),getattr(synced,"home_score","?"),getattr(synced,"away_score","?"),age,old_sig,new_sig,[(x.get('source'),x.get('odd')) for x in (fresh.get('source_prices') or [])],fresh.get('source_spread_pct'))
 if isinstance(recs,list):recs[:]=fresh_recs
 return _orig_send(synced,pressure,recs,text)

lc._send=_send
logger.info("CORE LIVE-only optional odds gate active max_age=%ss",MAX_QUOTE_AGE)
