"""Rank all verified GOOL LIVE markets and mark one concrete best bet.

The selector does not create signals. It only ranks markets already collected by
CORE and verified source adapters. The score combines model confidence, price,
value edge and independent market confirmation. BTTS is scored conservatively
until a dedicated side-goal probability model is calibrated from the journal.
"""
from __future__ import annotations
import math
import live_candidate_patch as lc
import unified_bot
_orig_market=lc._market

def _implied(odd):
 try:return max(1.0,min(99.0,100.0/float(odd)))
 except Exception:return 0.0

def _confirmation(row):
 status=str(row.get("external_market_status") or row.get("market_status") or row.get("market_consensus") or "")
 return {"STEAM":12.0,"CONFIRMED":8.0,"EARLY":1.0,"SINGLE_SOURCE":-2.0,"DISAGREE":-9.0,"CONFLICT":-14.0}.get(status,0.0)

def _price_quality(odd):
 try:o=float(odd)
 except Exception:return -20.0
 if o<1.05 or o>6.0:return -20.0
 if 1.35<=o<=2.40:return 5.0
 if 1.20<=o<1.35 or 2.40<o<=3.20:return 2.0
 if o>4.0:return -5.0
 return 0.0

def _model_conf(row,m,p):
 try:
  if row.get("confidence") is not None:return float(row.get("confidence"))
  odd=float(row.get("odd"));scope=str(row.get("scope") or "FULL_TIME")
  if row.get("market_type")=="FIRST_HALF_GOAL":
   line=float(row.get("line"));goals=int(m.home_score or 0)+int(m.away_score or 0)
   return float(unified_bot._model_confidence(p.score,p.momentum,line,goals,"FIRST_HALF",m.minute,odd))
  if row.get("market_type")=="BTTS":
   # Conservative proxy. True BTTS calibration will replace this after journal backfill.
   market=_implied(odd);pressure=float(getattr(p,"score",0) or 0);mom=float(getattr(p,"momentum",0) or 0)
   one_scored=(int(m.home_score or 0)>0) ^ (int(m.away_score or 0)>0)
   return max(5.0,min(88.0,market*.45+pressure*.35+mom*.20+(5.0 if one_scored else 0.0)))
 except Exception:pass
 return float(getattr(p,"score",0) or 0)*.65

def _rank(row,m,p):
 try:odd=float(row.get("odd"))
 except Exception:return -999.0,{}
 conf=_model_conf(row,m,p);imp=_implied(odd);edge=float(row.get("value_edge") or (conf-imp));sources=int(row.get("source_count") or row.get("bookmakers") or 1)
 score=conf*.58+max(-15.0,min(20.0,edge))*.65+_confirmation(row)+_price_quality(odd)+min(6.0,max(0,sources-1)*3.0)
 kind=str(row.get("market_type") or "TOTAL")
 if kind=="BTTS" and sources<2:score-=7.0
 if kind=="BTTS" and int(m.minute or 0)>=75:score-=5.0
 if kind=="FIRST_HALF_GOAL":
  rem=max(0,47-int(m.minute or 0));score+=4.0 if 8<=rem<=30 else -4.0 if rem<5 else 0.0
 if str(row.get("external_market_status") or row.get("market_status") or "") in {"CONFLICT","DISAGREE"}:score-=4.0
 meta={"selector_score":round(score,1),"selector_confidence":round(conf,1),"selector_implied":round(imp,1),"selector_edge":round(edge,1)}
 return score,meta

def _market(entries,m,p):
 recs,market=_orig_market(entries,m,p)
 for r in recs:
  r.pop("best_concrete_bet",None)
 ranked=[]
 for r in recs:
  if r.get("scope") not in {"FULL_TIME","FIRST_HALF"}:continue
  if r.get("odd") is None:continue
  score,meta=_rank(r,m,p);r.update(meta)
  if score>-900:ranked.append((score,r))
 ranked.sort(key=lambda x:x[0],reverse=True)
 if ranked:
  best=ranked[0][1];best["best_concrete_bet"]=True
  market["best_concrete_bet"]={k:best.get(k) for k in ("scope","market_type","extra_market","line","selection","odd","source","source_prices","selector_score","selector_confidence","selector_edge")}
  market["best_alternatives"]=[{k:r.get(k) for k in ("scope","market_type","extra_market","line","selection","odd","source","selector_score")} for _,r in ranked[1:3]]
 return recs,market
lc._market=_market
