"""Lightweight multi-source money-flow scoring for GOOL.

Adds breadth, velocity, persistence, reversal and event-reset semantics while
keeping a strictly bounded in-memory history. No browser/database/new dependency.
"""
from __future__ import annotations
import time
_HISTORY={};_MAX_POINTS=8;_TTL=1800;_MAX_KEYS=400

def _f(v,d=0.):
 try:return float(v)
 except Exception:return d

def _dir(sp):
 mv=(sp or {}).get("movement") or {};return str(mv.get("direction") or "flat"),_f(mv.get("drop_pct"))
def _src(sp,i):return str(sp.get("bookmaker") or sp.get("source") or sp.get("provider") or f"src{i}")
def _odd(sp):
 for k in ("odd","odds","price","last_odds","current_odds"):
  x=_f(sp.get(k),0)
  if x>1:return x
 return 0.
def _row_key(row,event_id):return f"{event_id or 'unknown'}|{row.get('market_type') or row.get('market')}|{row.get('selection')}|{row.get('team_side')}|{row.get('line')}"
def _reset_if_needed(key,score,minute):
 h=_HISTORY.get(key)
 if not h:return
 if score is not None and h.get("score") is not None and str(score)!=str(h.get("score")):_HISTORY.pop(key,None);return
 if minute is not None and h.get("minute") is not None and int(minute)<int(h.get("minute")):_HISTORY.pop(key,None)
def _evict_if_needed():
 if len(_HISTORY)<_MAX_KEYS:return
 oldest=sorted(_HISTORY,key=lambda k:((_HISTORY[k].get("points") or [(0,{})])[-1][0]))[:max(1,len(_HISTORY)-_MAX_KEYS+1)]
 for k in oldest:_HISTORY.pop(k,None)
def _remember(row,event_id=None,score=None,minute=None):
 key=_row_key(row,event_id);_reset_if_needed(key,score,minute);now=time.time();prices=row.get("source_prices") or [];snap={_src(sp,i):_odd(sp) for i,sp in enumerate(prices) if _odd(sp)>1}
 if key not in _HISTORY:_evict_if_needed()
 h=_HISTORY.setdefault(key,{"points":[],"score":score,"minute":minute});h["score"]=score;h["minute"]=minute;h["points"].append((now,snap));h["points"]=h["points"][-_MAX_POINTS:];return h

def score_row(row:dict,event_id=None,score=None,minute=None)->dict:
 prices=row.get("source_prices") or [];toward=against=0;drops=[]
 for sp in prices:
  d,p=_dir(sp);drops.append(p);toward+=int(d=="toward" and p>=0.5);against+=int(d=="against" and p<=-0.5)
 n=len(prices);strongest=max(drops) if drops else 0.;weakest=min(drops) if drops else 0.;h=_remember(row,event_id,score,minute);pts=h.get("points") or []
 breadth=(toward/max(1,n))*100 if n else 0.;velocity=0.;reversal=0.;persistent=0
 if len(pts)>=2:
  t0,s0=pts[0];t1,s1=pts[-1];dt=max(1.,t1-t0);moves=[]
  for src,o0 in s0.items():
   o1=s1.get(src)
   if o0>1 and o1 and o1>1:moves.append((o0-o1)/o0*100)
  if moves:
   mean=sum(moves)/len(moves);velocity=max(-100.,min(100.,mean*60/dt*10));persistent=sum(1 for x in moves if x>=.5)
   for src,o1 in s1.items():
    hist=[s.get(src) for _,s in pts[:-1] if s.get(src)]
    if hist:
     best=min(hist)
     if o1>best*1.015:reversal+=1
 persistence=(persistent/max(1,n))*100 if n else 0.;reversal_share=(reversal/max(1,n))*100 if n else 0.
 if n>=3 and toward>=3:status="CONFIRMED_MONEY_FLOW";base=8.
 elif n>=2 and toward>=2:status="CONFIRMED_STEAM";base=6.
 elif toward>=1:status="STEAM";base=2.
 elif against>toward:status="REVERSAL";base=-4.
 else:status="STABLE";base=0.
 score_pts=base+min(5.,max(0.,strongest)*.55)+min(4.,breadth*.04)+min(3.,max(0.,velocity)*.03)+min(3.,persistence*.03)-min(8.,reversal_share*.08)
 if against>toward:score_pts=min(score_pts,-3.)
 return {"movement_status":status,"movement_score":round(max(-12.,min(20.,score_pts)),1),"movement_sources":n,"movement_toward":toward,"movement_against":against,"movement_drop_pct":round(strongest,2),"flow_breadth":round(breadth,1),"flow_velocity":round(velocity,1),"flow_persistence":round(persistence,1),"flow_reversal":round(reversal_share,1)}
def annotate(rows:list[dict],event_id=None,score=None,minute=None)->list[dict]:
 now=time.time()
 for k in list(_HISTORY):
  p=_HISTORY[k].get("points") or []
  if not p or now-p[-1][0]>_TTL:_HISTORY.pop(k,None)
 for r in rows:r.update(score_row(r,event_id,score,minute))
 goalish=[r for r in rows if str(r.get("market_type") or "TOTAL") in {"TOTAL","BTTS","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and r.get("movement_status") in {"STEAM","CONFIRMED_STEAM","CONFIRMED_MONEY_FLOW"}]
 families={str(r.get("market_type") or "TOTAL") for r in goalish};correlated=len(families)>=2
 if correlated:
  for r in goalish:r["correlated_steam"]=True;r["movement_score"]=round(min(22.,_f(r.get("movement_score"))+3.),1)
 return rows
