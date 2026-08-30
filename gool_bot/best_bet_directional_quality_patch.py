"""Directional quality correction for BEST BET.

The base BEST BET score historically used a generic live-pressure/context score and an
OVER-oriented history score for every market direction. That could incorrectly boost
UNDER/BTTS-NO selections in hot, high-scoring matches. This patch makes those inputs
selection-aware while preserving model probability, value and market-flow evidence.
"""
from __future__ import annotations
import inspect,logging
import best_bet_engine as bbe
from best_bet_calibration import penalty_for

log=logging.getLogger("best_bet_directional_quality")
_ORIG_RANK=bbe._rank

def _f(v,d=0.0):
    try:return float(v)
    except Exception:return d

def _call_orig(r,m,p,hist):
    try:n=len(inspect.signature(_ORIG_RANK).parameters)
    except Exception:n=4
    return _ORIG_RANK(r,m,p,hist) if n>=4 else _ORIG_RANK(r,m,p)

def _direction(side,ctx,hist):
    if side in {"UNDER","NO"}:
        return max(0.0,min(100.0,100.0-ctx)),max(0.0,min(100.0,100.0-hist))
    return ctx,hist

def _risk_penalty(r,m,p,side):
    """Extra protection against UNDER in an actively open match."""
    if side!="UNDER":return 0.0
    try:
        line=float(r.get("line"));goals=int(getattr(m,"home_score",0) or 0)+int(getattr(m,"away_score",0) or 0);minute=int(getattr(m,"minute",0) or 0)
    except Exception:return 0.0
    pressure=max(_f(getattr(p,"score",0)),_f(getattr(p,"momentum",0)))
    buffer=line-goals
    penalty=0.0
    # With only one-goal safety margin left, a hot game must not be promoted as an UNDER
    # merely because the model/value component is high.
    if minute<78 and buffer<=1.5 and pressure>=60:penalty+=10.0
    if minute<72 and buffer<=1.5 and pressure>=72:penalty+=6.0
    return penalty

def rank(r,m,p,hist=None):
    x=_call_orig(r,m,p,hist)
    if not x:return x
    side=bbe._side(r)
    if side not in {"OVER","UNDER","YES","NO"}:return x
    raw_ctx=_f(x.get("context"),50.0);raw_hist=_f(x.get("history_score"),50.0)
    ctx,hscore=_direction(side,raw_ctx,raw_hist)
    model_pct=_f(x.get("confidence"));edge=_f(x.get("edge"));flow_score=_f(x.get("market_score"),50.0);status=str(x.get("status") or "PRIMARY").upper();cal,_=penalty_for(r)
    value_score=max(0.0,min(100.0,50.0+edge*3.0))
    score=model_pct*.34+ctx*.24+hscore*.20+value_score*.14+flow_score*.08+cal
    if status in {"CONFLICT","DISAGREE"}:score-=7
    elif status=="REVERSAL":score-=5
    elif status in {"CONFIRMED_MONEY_FLOW","CONFIRMED_STEAM"}:score+=3
    if bool(x.get("suspicious")):score-=20
    risk=_risk_penalty(r,m,p,side);score-=risk
    x["score"]=round(max(0.0,min(100.0,score)),1)
    x["context_raw"]=round(raw_ctx,1);x["history_score_raw"]=round(raw_hist,1)
    x["context"]=round(ctx,1);x["history_score"]=round(hscore,1)
    x["directional_quality"]=True;x["directional_risk_penalty"]=round(risk,1)
    return x

bbe._rank=rank
log.info("BEST BET directional quality active | UNDER/NO invert hot-live + high-total history | hot-under guard=on")
