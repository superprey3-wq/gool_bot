"""Candidate-only Kambi confirmation for Flashscore/LSApp LIVE totals.

Flashscore/LSApp creates every actionable line. Kambi/BetRivers may confirm the
same line and contribute movement/consensus, but never creates or replaces it.
"""
from __future__ import annotations
import time
from collections import defaultdict,deque
import live_candidate_patch as lc
from kambi_live_odds import get_live_goal_totals

_HISTORY:dict[str,deque]=defaultdict(lambda:deque(maxlen=4));_TTL=45*60
_orig_target=lc._target_goal_markets

def _standard(line):
    try:return abs(float(line)*2-round(float(line)*2))<1e-9
    except Exception:return False

def _track(key,odd):
    now=time.time();q=_HISTORY[key]
    while q and now-q[0][0]>_TTL:q.popleft()
    if not q or abs(q[-1][1]-odd)>1e-6 or now-q[-1][0]>=20:q.append((now,float(odd)))
    if len(q)<2:return {"direction":"flat","from":round(odd,3),"to":round(odd,3),"drop_pct":0.0}
    old,new=float(q[0][1]),float(q[-1][1]);drop=(old-new)/old*100 if old>1 else 0
    return {"direction":"toward" if drop>.5 else "against" if drop<-.5 else "flat","from":round(old,3),"to":round(new,3),"drop_pct":round(drop,2)}

def _target_with_multi(entries,m,p):
    rows=_orig_target(entries,m,p)
    if not rows:return rows
    try:krows=get_live_goal_totals(m.home,m.away)
    except Exception:krows=[]
    kby={float(x.get("line")):x for x in krows if x.get("scope")=="FULL_TIME" and _standard(x.get("line")) and lc._sane_price(x)}
    for r in rows:
        if str(r.get("scope") or "")!="FULL_TIME":continue
        try:line=float(r.get("line"));base=float(r.get("odd"))
        except (TypeError,ValueError):continue
        if not _standard(line):continue
        sources=[{"source":"Flashscore/LSApp","odd":base}]
        kr=kby.get(line)
        if kr:sources.append({"source":"Kambi/BetRivers","odd":float(kr["odd"])})
        moves=[]
        for s in sources:
            mv=_track(f"{m.event_id}|{line:g}|{s['source']}",float(s['odd']));s["movement"]=mv;moves.append(mv)
        r["source"]="Flashscore/LSApp";r["primary_source"]="Flashscore/LSApp";r["source_prices"]=sources;r["source_count"]=len(sources)
        if len(sources)>=2:
            vals=[float(x["odd"]) for x in sources];spread=(max(vals)-min(vals))/min(vals)*100 if min(vals)>0 else 999
            r["market_consensus"]="CONFIRMED" if spread<=12 else "DISAGREE";r["source_spread_pct"]=round(spread,2);r["bookmakers"]=max(int(r.get("bookmakers") or 1),len(sources))
        else:r["market_consensus"]="PRIMARY_ONLY"
        toward=sum(x.get("direction")=="toward" for x in moves);against=sum(x.get("direction")=="against" for x in moves)
        r["external_market_status"]="STEAM" if len(moves)>=2 and toward>=2 else "CONFLICT" if against>toward else "EARLY"
    return rows

lc._target_goal_markets=_target_with_multi
