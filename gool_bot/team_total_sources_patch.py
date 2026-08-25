"""Confirmation-only team-total enrichment.

Team totals are actionable only when Flashscore/LSApp already supplied the exact
market. Kambi/BetRivers may confirm the same team/line; it never creates a team
total candidate on its own.
"""
from __future__ import annotations
import live_candidate_patch as lc
from kambi_live_odds import _find_event as kam_find,_event_data as kam_event,_sim as kam_sim

_orig_market=lc._market

def _kambi(home,away):
    try:e=kam_find(home,away)
    except Exception:e=None
    if not e:return []
    try:data=kam_event(str(e.get("id")))
    except Exception:return []
    out=[]
    for offer in data.get("betOffers") or []:
        tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");text=f"{tn} {cr}";low=text.lower()
        if not ("total goals by" in low or "team total" in low):continue
        if any(x in low for x in ("asian","corner","card","booking","shot","1st half","first half","2nd half","second half")):continue
        side="HOME" if kam_sim(text,home)>=kam_sim(text,away) else "AWAY"
        if max(kam_sim(text,home),kam_sim(text,away))<.28:continue
        for o in offer.get("outcomes") or []:
            if o.get("status")!="OPEN":continue
            label=str(o.get("label") or "").lower();typ=str(o.get("type") or "")
            if "over" not in label and typ!="OT_OVER":continue
            try:line=float(o.get("line"))/1000;odd=float(o.get("odds"))/1000
            except (TypeError,ValueError):continue
            if odd>1.001 and abs(line*2-round(line*2))<1e-9:out.append({"team_side":side,"line":line,"odd":odd})
    return out

def _market(entries,m,p):
    recs,market=_orig_market(entries,m,p)
    try:krows=_kambi(m.home,m.away)
    except Exception:krows=[]
    for r in recs:
        kind=str(r.get("market_type") or "").upper()
        if kind not in {"TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"}:continue
        if str(r.get("primary_source") or r.get("source") or "") not in {"Flashscore/LSApp","LSApp"}:continue
        side="HOME" if kind.endswith("HOME") else "AWAY"
        try:line=float(r.get("line"));base=float(r.get("odd"))
        except (TypeError,ValueError):continue
        k=next((x for x in krows if x.get("team_side")==side and abs(float(x.get("line"))-line)<1e-9),None)
        if not k:continue
        other=float(k["odd"]);r["source"]="Flashscore/LSApp";r["primary_source"]="Flashscore/LSApp";r["source_prices"]=[{"source":"Flashscore/LSApp","odd":base},{"source":"Kambi/BetRivers","odd":other}];r["source_count"]=2
        spread=abs(other-base)/min(base,other)*100 if min(base,other)>0 else 999;r["source_spread_pct"]=round(spread,2);r["market_status"]="CONFIRMED" if spread<=15 else "DISAGREE"
    return recs,market

lc._market=_market
