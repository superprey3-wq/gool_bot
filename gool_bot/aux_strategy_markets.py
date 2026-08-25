"""Verified market helpers for GOOL auxiliary strategies.

Uses the already-tested public Bovada and Kambi feeds. Only standard integer/
half goal totals are accepted; Asian quarter lines are excluded upstream.
"""
from __future__ import annotations
from typing import Any

from bovada_live_odds import _find_event as bov_find, _over_prices as bov_over
from kambi_live_odds import _find_event as kam_find, _event_data as kam_event, _scope_from_offer


def _clean(row):
    if not row:return None
    try:
        odd=float(row.get("odd"));line=float(row.get("line"))
    except (TypeError,ValueError):return None
    if odd<=1.001:return None
    if abs(line*2-round(line*2))>1e-9:return None
    return dict(row,odd=odd,line=line)


def first_half_next_total(home:str,away:str,current_goals:int)->list[dict[str,Any]]:
    """Current 1H total after score: 0 goals->O0.5, 1->O1.5, 2->O2.5..."""
    target=float(int(current_goals)+0.5);rows=[]
    try:
        e=bov_find(home,away)
        if e:
            vals=bov_over(e,"FIRST_HALF").get(target,[])
            if vals:rows.append({"scope":"FIRST_HALF","line":target,"odd":float(min(vals)),"source":"Bovada"})
    except Exception:pass
    try:
        e=kam_find(home,away)
        if e:
            data=kam_event(str(e.get("id")))
            for offer in data.get("betOffers") or []:
                tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");key=f"{tn} {cr}".lower()
                if _scope_from_offer(cr,tn)!="FIRST_HALF":continue
                if not any(x in key for x in ("over/under","total goals")) or any(x in key for x in ("asian"," by ","corner","card","shot","booking")):continue
                for o in offer.get("outcomes") or []:
                    if o.get("status")!="OPEN":continue
                    lab=str(o.get("label") or "").lower();typ=str(o.get("type") or "")
                    if "over" not in lab and typ!="OT_OVER":continue
                    try:line=float(o.get("line"))/1000;odd=float(o.get("odds"))/1000
                    except (TypeError,ValueError):continue
                    if abs(line-target)<1e-9:rows.append({"scope":"FIRST_HALF","line":line,"odd":odd,"source":"Kambi/BetRivers"})
    except Exception:pass
    return [x for x in (_clean(r) for r in rows) if x]


def second_half_over15(home:str,away:str)->list[dict[str,Any]]:
    """Standard second-half Over 1.5 market from verified feeds."""
    target=1.5;rows=[]
    try:
        e=bov_find(home,away)
        if e:
            vals=bov_over(e,"SECOND_HALF").get(target,[])
            if vals:rows.append({"scope":"SECOND_HALF","line":target,"odd":float(min(vals)),"source":"Bovada"})
    except Exception:pass
    try:
        e=kam_find(home,away)
        if e:
            data=kam_event(str(e.get("id")))
            for offer in data.get("betOffers") or []:
                tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");key=f"{tn} {cr}".lower()
                if _scope_from_offer(cr,tn)!="SECOND_HALF":continue
                if not any(x in key for x in ("over/under","total goals")) or any(x in key for x in ("asian"," by ","corner","card","shot","booking")):continue
                for o in offer.get("outcomes") or []:
                    if o.get("status")!="OPEN":continue
                    lab=str(o.get("label") or "").lower();typ=str(o.get("type") or "")
                    if "over" not in lab and typ!="OT_OVER":continue
                    try:line=float(o.get("line"))/1000;odd=float(o.get("odds"))/1000
                    except (TypeError,ValueError):continue
                    if abs(line-target)<1e-9:rows.append({"scope":"SECOND_HALF","line":line,"odd":odd,"source":"Kambi/BetRivers"})
    except Exception:pass
    return [x for x in (_clean(r) for r in rows) if x]


def best_consensus(rows:list[dict[str,Any]])->dict[str,Any]|None:
    rows=[r for r in rows if r]
    if not rows:return None
    odds=[float(r["odd"]) for r in rows];best=max(rows,key=lambda r:float(r["odd"]));best=dict(best)
    best["source_prices"]=[{"source":r["source"],"odd":float(r["odd"])} for r in rows]
    best["source_count"]=len(rows)
    if len(rows)>=2:
        spread=(max(odds)-min(odds))/min(odds)*100 if min(odds)>0 else 999
        best["market_status"]="CONFIRMED" if spread<=15 else "DISAGREE"
    else:best["market_status"]="SINGLE_SOURCE"
    return best
