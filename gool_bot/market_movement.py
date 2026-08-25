"""Lightweight market-movement scoring for GOOL.

Consumes normalized recommendation rows that already contain source_prices and
per-source movement snapshots. No browser, no database, tiny CPU/RAM footprint.
"""
from __future__ import annotations

def _dir(sp):
    mv=(sp or {}).get("movement") or {}
    return str(mv.get("direction") or "flat"), float(mv.get("drop_pct") or 0.0)

def score_row(row:dict)->dict:
    prices=row.get("source_prices") or []
    toward=against=0; drops=[]
    for sp in prices:
        d,p=_dir(sp);drops.append(p)
        toward += int(d=="toward" and p>=0.5)
        against += int(d=="against" and p<=-0.5)
    n=len(prices)
    strongest=max(drops) if drops else 0.0
    weakest=min(drops) if drops else 0.0
    if n>=2 and toward>=2:
        status="CONFIRMED_STEAM"; pts=min(12.0,6.0+strongest*.7)
    elif toward>=1:
        status="STEAM"; pts=min(7.0,2.0+strongest*.6)
    elif against>toward:
        status="REVERSAL"; pts=max(-10.0,-3.0+weakest*.7)
    else:
        status="STABLE"; pts=0.0
    return {"movement_status":status,"movement_score":round(pts,1),"movement_sources":n,"movement_toward":toward,"movement_against":against,"movement_drop_pct":round(strongest,2)}

def annotate(rows:list[dict])->list[dict]:
    # First score each market independently.
    for r in rows:r.update(score_row(r))
    # Then detect correlated goal-side steam across different market families.
    goalish=[r for r in rows if str(r.get("market_type") or "TOTAL") in {"TOTAL","BTTS","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and r.get("movement_status") in {"STEAM","CONFIRMED_STEAM"}]
    families={str(r.get("market_type") or "TOTAL") for r in goalish}
    correlated=len(families)>=2
    if correlated:
        for r in goalish:
            r["correlated_steam"]=True
            r["movement_score"]=round(min(15.0,float(r.get("movement_score") or 0)+3.0),1)
    return rows
