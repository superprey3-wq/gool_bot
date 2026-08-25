"""Merge SportsGameOdds prices into existing GOOL candidate markets.

The provider is optional and never creates a signal. Matching rows only add an
extra bookmaker/source and opening-line context to a market GOOL already found.
"""
from __future__ import annotations
import live_candidate_patch as lc
import sportsgameodds_provider as sgo
_orig=lc._market

def _same(a,b):
 if str(a.get("scope"))!="FULL_TIME" or str(b.get("scope"))!="FULL_TIME":return False
 if str(a.get("market_type") or "TOTAL")!=str(b.get("market_type") or "TOTAL"):return False
 if str(a.get("team_side") or "")!=str(b.get("team_side") or ""):return False
 try:return abs(float(a.get("line"))-float(b.get("line")))<1e-9
 except:return False

def _market(entries,m,p):
 recs,market=_orig(entries,m,p)
 if not sgo.enabled():return recs,market
 try:extra=sgo.rows(m.home,m.away)
 except Exception:extra=[]
 for r in recs:
  hits=[x for x in extra if _same(r,x)]
  if not hits:continue
  prices=list(r.get("source_prices") or [])
  for h in hits:
   for sp in h.get("source_prices") or []:
    if not any(str(x.get("source"))==str(sp.get("source")) for x in prices):prices.append(sp)
  r["source_prices"]=prices;r["source_count"]=len(prices);r["bookmakers"]=max(int(r.get("bookmakers") or 1),len(prices));r["sgo_confirmed"]=True
 return recs,market
lc._market=_market
