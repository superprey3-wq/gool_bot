"""Flashscore-first verified market helpers for GOOL auxiliary strategies.

Flashscore/LSApp must provide the exact period line. Kambi/BetRivers can confirm
that same line, but external data never creates an auxiliary market by itself.
"""
from __future__ import annotations
from typing import Any
from live_odds import fetch_live_odds
from kambi_live_odds import _find_event as kam_find,_event_data as kam_event,_scope_from_offer


def _clean(row):
    if not row:return None
    try:odd=float(row.get("odd"));line=float(row.get("line"))
    except (TypeError,ValueError):return None
    if odd<=1.001 or abs(line*2-round(line*2))>1e-9:return None
    return dict(row,odd=odd,line=line)


def _ls_period(event_id,scope,target):
    rows=[]
    try:entries=fetch_live_odds(str(event_id))
    except Exception:entries=[]
    for entry in entries or []:
        if str(entry.get("bettingScope") or "")!=scope:continue
        for item in entry.get("odds") or []:
            if str(item.get("selection") or "").upper()!="OVER" or item.get("active") is False:continue
            try:line=float((item.get("handicap") or {}).get("value"));odd=float(item.get("value"))
            except (TypeError,ValueError,AttributeError):continue
            if abs(line-target)<1e-9 and odd>1.001:rows.append({"scope":scope,"line":line,"odd":odd,"source":"Flashscore/LSApp","primary_source":True})
    return rows


def _kambi_period(home,away,scope,target):
    rows=[]
    try:e=kam_find(home,away)
    except Exception:e=None
    if not e:return rows
    try:data=kam_event(str(e.get("id")))
    except Exception:return rows
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
            if abs(line-target)<1e-9 and odd>1.001:rows.append({"scope":scope,"line":line,"odd":odd,"source":"Kambi/BetRivers"})
    return rows


def first_half_next_total(event_id:str,home:str,away:str,current_goals:int)->list[dict[str,Any]]:
    target=float(int(current_goals)+.5);primary=_ls_period(event_id,"FIRST_HALF",target)
    if not primary:return []
    return [x for x in (_clean(r) for r in primary+_kambi_period(home,away,"FIRST_HALF",target)) if x]


def second_half_over15(event_id:str,home:str,away:str)->list[dict[str,Any]]:
    target=1.5;primary=_ls_period(event_id,"SECOND_HALF",target)
    if not primary:return []
    return [x for x in (_clean(r) for r in primary+_kambi_period(home,away,"SECOND_HALF",target)) if x]


def best_consensus(rows:list[dict[str,Any]])->dict[str,Any]|None:
    rows=[r for r in rows if r]
    primary=next((r for r in rows if str(r.get("source"))=="Flashscore/LSApp"),None)
    if not primary:return None
    best=dict(primary);odds=[float(r["odd"]) for r in rows]
    best["source_prices"]=[{"source":r["source"],"odd":float(r["odd"])} for r in rows];best["source_count"]=len(rows);best["primary_source"]="Flashscore/LSApp"
    if len(rows)>=2:
        spread=(max(odds)-min(odds))/min(odds)*100 if min(odds)>0 else 999;best["market_status"]="CONFIRMED" if spread<=15 else "DISAGREE"
    else:best["market_status"]="PRIMARY_ONLY"
    return best
