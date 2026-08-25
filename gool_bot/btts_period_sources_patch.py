"""Confirmation-only side-market enrichment.

GOOL no longer creates BTTS or period markets from external bookmakers. If an
exact Flashscore/LSApp row already exists in the candidate set, Kambi may add a
second price for confirmation. Otherwise the market is absent.
"""
from __future__ import annotations
import live_candidate_patch as lc
from kambi_live_odds import get_btts_yes,get_live_goal_totals

_orig_market=lc._market

def _same_period_kambi(m,row):
    try:line=float(row.get("line"));scope=str(row.get("scope") or "")
    except (TypeError,ValueError):return None
    try:rows=get_live_goal_totals(m.home,m.away)
    except Exception:return None
    return next((x for x in rows if str(x.get("scope") or "")==scope and x.get("line") is not None and abs(float(x.get("line"))-line)<1e-9),None)

def _market(entries,m,p):
    recs,market=_orig_market(entries,m,p)
    for r in recs:
        # Only rows already created by Flashscore/LSApp are eligible for enrichment.
        if str(r.get("primary_source") or r.get("source") or "") not in {"Flashscore/LSApp","LSApp"}:continue
        kind=str(r.get("market_type") or "").upper();extra=None
        if kind=="BTTS":
            try:extra=get_btts_yes(m.home,m.away)
            except Exception:extra=None
        elif str(r.get("scope") or "") in {"FIRST_HALF","SECOND_HALF"} and r.get("line") is not None:
            extra=_same_period_kambi(m,r)
        if not extra:continue
        try:base=float(r.get("odd"));other=float(extra.get("odd"))
        except (TypeError,ValueError):continue
        r["source"]="Flashscore/LSApp";r["primary_source"]="Flashscore/LSApp";r["source_prices"]=[{"source":"Flashscore/LSApp","odd":base},{"source":"Kambi/BetRivers","odd":other}];r["source_count"]=2
        spread=abs(other-base)/min(base,other)*100 if min(base,other)>0 else 999;r["source_spread_pct"]=round(spread,2);r["market_status"]="CONFIRMED" if spread<=12 else "DISAGREE"
    return recs,market

lc._market=_market
