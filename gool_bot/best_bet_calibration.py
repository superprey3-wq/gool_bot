"""Lightweight journal calibration/drift guard for BEST BET.

No training job is run in production. Metrics are cached for five minutes and
only penalize a market after a meaningful settled sample exists.
"""
from __future__ import annotations
import time
from signal_journal import all_signals
_CACHE=(0.0,{})
def _group(row):
 p=row.get("primary") or {};k=str(p.get("market_type") or p.get("market") or "OTHER").upper()
 if "TOTAL" in k and not k.startswith("TEAM"):return "TOTAL"
 if k.startswith("TEAM_TOTAL"):return "TEAM_TOTAL"
 if k=="BTTS":return "BTTS"
 if k in {"HOME","AWAY","DRAW","1X","X2","12","DNB_HOME","DNB_AWAY"}:return "RESULT"
 return k or "OTHER"
def metrics():
 global _CACHE
 now=time.time()
 if now-_CACHE[0]<300:return _CACHE[1]
 agg={}
 for r in all_signals():
  result=str(r.get("result") or "")
  if r.get("kind")!="best_bet" or result not in {"win","loss","push"}:continue
  g=_group(r);a=agg.setdefault(g,{"n":0,"wins":0,"losses":0,"pushes":0,"pnl":0.0,"clv":[]});a["n"]+=1;a[{"win":"wins","loss":"losses","push":"pushes"}[result]]+=1
  try:a["pnl"]+=float(r.get("bet_pnl_units") or 0)
  except Exception:pass
  for key in ("clv_120_implied_pp","clv_60_implied_pp"):
   if r.get(key) is not None:
    try:a["clv"].append(float(r[key]));break
    except Exception:pass
 for a in agg.values():
  a["roi_pct"]=round(a["pnl"]/max(1,a["n"])*100,1);a["avg_clv_pp"]=round(sum(a["clv"])/len(a["clv"]),2) if a["clv"] else None
 _CACHE=(now,agg);return agg
def penalty_for(row):
 a=metrics().get(_group({"primary":row})) or {};n=int(a.get("n",0) or 0)
 if n<20:return 0.0,"learning"
 roi=float(a.get("roi_pct",0) or 0);clv=a.get("avg_clv_pp");pen=0.0
 if roi<-5:pen-=3
 if roi<-10:pen-=5
 if clv is not None and float(clv)<-1:pen-=3
 if n>=40 and roi<-12 and clv is not None and float(clv)<-2:return -25.0,"auto_pause"
 return pen,"calibrated"
