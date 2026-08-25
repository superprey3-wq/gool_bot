"""Optional SportsGameOdds v2 provider for candidate-only GOOL confirmation.

Disabled when SPORTSGAMEODDS_KEY is absent. Fetches live soccer events with a
short cache, fuzzy-matches a GOOL candidate, and exposes only standard full-time
Over and team-total Over markets. It never creates a candidate by itself.
"""
from __future__ import annotations
import os,time,re,requests
from difflib import SequenceMatcher
KEY=os.getenv("SPORTSGAMEODDS_KEY","").strip();BASE="https://api.sportsgameodds.com/v2";TTL=max(60,int(os.getenv("SPORTSGAMEODDS_TTL","180")));_cache=(0.0,[])
def enabled():return bool(KEY)
def _norm(s):return re.sub(r"[^a-z0-9]+","",str(s or "").lower())
def _sim(a,b):
 a,b=_norm(a),_norm(b)
 return SequenceMatcher(None,a,b).ratio() if a and b else 0.0
def _dec(x):
 try:a=float(x)
 except:return None
 if a>=100:return round(1+a/100,4)
 if a<=-100:return round(1+100/abs(a),4)
 if 1<a<20:return a
 return None
def _events():
 global _cache
 if not KEY:return []
 now=time.time()
 if now-_cache[0]<TTL:return _cache[1]
 try:
  r=requests.get(BASE+"/events",params={"sportID":"SOCCER","live":"true","oddsAvailable":"true","includeOpenCloseOdds":"true"},headers={"x-api-key":KEY},timeout=10)
  rows=(r.json().get("data") or []) if r.ok else []
 except Exception:rows=[]
 _cache=(now,rows);return rows
def _match(home,away):
 best=None;bs=0.0
 for e in _events():
  t=e.get("teams") or {};h=((t.get("home") or {}).get("names") or {}).get("long") or ((t.get("home") or {}).get("names") or {}).get("medium");a=((t.get("away") or {}).get("names") or {}).get("long") or ((t.get("away") or {}).get("names") or {}).get("medium")
  s=(_sim(home,h)+_sim(away,a))/2
  if s>bs:best,bs=e,s
 return best if bs>=.72 else None
def rows(home,away):
 e=_match(home,away);out=[]
 if not e:return out
 for oid,o in (e.get("odds") or {}).items():
  if str(o.get("betTypeID"))!="ou" or str(o.get("sideID"))!="over" or str(o.get("periodID"))!="game":continue
  ent=str(o.get("statEntityID") or "");line=o.get("bookOverUnder")
  books=[]
  for bid,b in (o.get("byBookmaker") or {}).items():
   if not b.get("available"):continue
   odd=_dec(b.get("odds"));ln=b.get("overUnder") if b.get("overUnder") is not None else line
   try:ln=float(ln)
   except:continue
   if odd and abs(ln*2-round(ln*2))<1e-9:books.append({"source":f"SGO/{bid}","odd":odd,"line":ln,"open_odd":_dec(b.get("openOdds")),"open_line":b.get("openOverUnder")})
  if not books:continue
  # One normalized price per line: use the best current decimal price, retain all books.
  byline={}
  for b in books:byline.setdefault(float(b["line"]),[]).append(b)
  for ln,bs in byline.items():
   side="HOME" if ent=="home" else "AWAY" if ent=="away" else None
   kind="TOTAL" if ent=="all" else f"TEAM_TOTAL_{side}" if side else None
   if not kind:continue
   out.append({"scope":"FULL_TIME","market_type":kind,"team_side":side,"line":ln,"odd":max(x["odd"] for x in bs),"source":"SportsGameOdds","source_prices":bs,"source_count":len(bs)})
 return out
