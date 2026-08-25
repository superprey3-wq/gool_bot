"""Verified market helpers for GOOL auxiliary strategies.

Bovada is intentionally disabled. Auxiliary 1H and 2H markets now use only the
verified Kambi/BetRivers feed. Only standard integer/half goal totals are accepted.
"""
from __future__ import annotations
from typing import Any
from kambi_live_odds import _find_event as kam_find, _event_data as kam_event, _scope_from_offer

def _clean(row):
    if not row:return None
    try:odd=float(row.get("odd"));line=float(row.get("line"))
    except (TypeError,ValueError):return None
    if odd<=1.001 or abs(line*2-round(line*2))>1e-9:return None
    return dict(row,odd=odd,line=line)
def _period_over(home,away,scope,target):
    rows=[]
    try:
        e=kam_find(home,away)
        if e:
            data=kam_event(str(e.get("id")))
            for offer in data.get("betOffers") or []:
                tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");key=f"{tn} {cr}".lower()
                if _scope_from_offer(cr,tn)!=scope:continue
                if not any(x in key for x in ("over/under","total goals")) or any(x in key for x in ("asian"," by ","corner","card","shot","booking")):continue
                for o in offer.get("outcomes") or []:
                    if o.get("status")!="OPEN":continue
                    lab=str(o.get("label") or "").lower();typ=str(o.get("type") or "")
                    if "over" not in lab and typ!="OT_OVER":continue
                    try:line=float(o.get("line"))/1000;odd=float(o.get("odds"))/1000
                    except (TypeError,ValueError):continue
                    if abs(line-target)<1e-9:rows.append({"scope":scope,"line":line,"odd":odd,"source":"Kambi/BetRivers"})
    except Exception:pass
    return [x for x in (_clean(r) for r in rows) if x]
def first_half_next_total(home:str,away:str,current_goals:int)->list[dict[str,Any]]:
    return _period_over(home,away,"FIRST_HALF",float(int(current_goals)+0.5))
def second_half_over15(home:str,away:str)->list[dict[str,Any]]:
    return _period_over(home,away,"SECOND_HALF",1.5)
def best_consensus(rows:list[dict[str,Any]])->dict[str,Any]|None:
    rows=[r for r in rows if r]
    if not rows:return None
    best=dict(max(rows,key=lambda r:float(r["odd"])))
    best["source_prices"]=[{"source":r["source"],"odd":float(r["odd"])} for r in rows]
    best["source_count"]=len(rows);best["market_status"]="SINGLE_SOURCE" if len(rows)==1 else "CONFIRMED"
    return best
