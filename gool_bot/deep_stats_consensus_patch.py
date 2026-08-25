"""Deepen non-odds LIVE validation from FotMob and 365Scores.

These sources contribute shotmap/xG/xGoT/statistics evidence to the analytical
score. They never read or use bookmaker prices and never create a market.
"""
from __future__ import annotations
import logging
import candidate_enrichment_patch as ce
import scores365_enrichment_patch as s365

logger=logging.getLogger("deep_stats_consensus")
_orig=ce._external_adjustment

def _external(match):
    adj,score,ext=_orig(match)
    reasons=ext.setdefault("reasons",[])
    score=float(score)
    try:fot=ce._fotmob_features(match)
    except Exception:fot={}
    try:sx=s365._features(match)
    except Exception:sx={}
    ext["fotmob_deep"]=fot
    ext["scores365_deep"]=sx

    ff=fot.get("features") or {}
    fxg=ff.get("shot_xg_total"); fxgot=ff.get("shot_xgot_total"); fshots=int(ff.get("shotmap_n") or 0)
    if fxg is not None:
        if float(fxg)>=1.8: score+=8; reasons.append(f"FotMob xG {float(fxg):.2f}")
        elif float(fxg)>=1.2: score+=5; reasons.append(f"FotMob xG {float(fxg):.2f}")
        elif float(fxg)<.30 and int(match.minute or 0)>=35: score-=6
    if fxgot is not None and float(fxgot)>=1.0: score+=6; reasons.append(f"FotMob xGoT {float(fxgot):.2f}")
    if fshots>=12: score+=3

    xg=sx.get("shot_xg_total"); xgot=sx.get("shot_xgot_total"); shots=int(sx.get("shots") or 0)
    if xg is not None:
        if float(xg)>=1.8: score+=8; reasons.append(f"365Scores xG {float(xg):.2f}")
        elif float(xg)>=1.2: score+=5; reasons.append(f"365Scores xG {float(xg):.2f}")
        elif float(xg)<.30 and int(match.minute or 0)>=35: score-=6
    if xgot is not None and float(xgot)>=1.0: score+=6; reasons.append(f"365Scores xGoT {float(xgot):.2f}")
    if shots>=12: score+=3

    # Cross-source agreement matters more than either source alone.
    if fxg is not None and xg is not None:
        gap=abs(float(fxg)-float(xg))
        if gap<=.35: score+=5; reasons.append("FotMob/365 xG consensus")
        elif gap>=1.0: score-=3; reasons.append("FotMob/365 xG disagreement")

    score=max(0.,min(100.,score))
    adj=round(max(-10.,min(10.,(score-50.)/5.5)),1)
    return adj,score,ext

ce._external_adjustment=_external
logger.info("Deep FotMob + 365Scores analytics enabled; odds not used")
