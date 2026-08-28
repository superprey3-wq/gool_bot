"""Prevent BEST BET from contradicting strong active GOOL specialist engines."""
from __future__ import annotations
import time
import best_bet_engine as bbe
from signal_journal import all_signals
_CACHE=(0.0,{})
def _active():
 global _CACHE
 now=time.time()
 if now-_CACHE[0]<20:return _CACHE[1]
 d={}
 for r in all_signals():
  if str(r.get("result") or "pending").lower()!="pending":continue
  eng=str(r.get("engine") or "")
  if eng not in {"FIRST_HALF_GOAL","SECOND_HALF_OVER15"}:continue
  try:score=float(r.get("strategy_score") or 0)
  except Exception:score=0
  if score<75:continue
  eid=str(r.get("event_id") or "");need=2 if eng=="SECOND_HALF_OVER15" else 1;d[eid]=max(d.get(eid,0),need)
 _CACHE=(now,d);return d
def _conflict(row,m):
 need=_active().get(str(getattr(m,"event_id","") or ""),0)
 if not need:return False
 side=bbe._side(row)
 if side!="UNDER":return False
 try:line=float(row.get("line"));current=int(getattr(m,"home_score",0) or 0)+int(getattr(m,"away_score",0) or 0)
 except Exception:return False
 # If the active specialist's minimum-goal scenario reaches/exceeds the UNDER
 # line, the two recommendations are directly incompatible or at best a push.
 return current+need>=line
_orig_rank=bbe._rank
def rank(row,m,p):
 x=_orig_rank(row,m,p)
 if x and _conflict(row,m):x["score"]=0.0;x["status"]="CONFLICT";x["specialist_conflict"]=True
 return x
bbe._rank=rank
