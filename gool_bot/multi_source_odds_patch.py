"""Candidate-only multi-source LIVE odds confirmation.

Adds verified Kambi/BetRivers prices beside the existing LSApp/Bovada candidate
market. It never creates a candidate by itself. Only standard .0/.5 totals are
accepted. Stores tiny in-memory micro-history per matched line to expose source
agreement and simple price movement without growing VPS memory.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

import live_candidate_patch as lc
from kambi_live_odds import get_live_goal_totals

_HISTORY: dict[str, deque] = defaultdict(lambda: deque(maxlen=4))
_TTL = 45 * 60
_orig_target = lc._target_goal_markets


def _standard(line: float) -> bool:
    return abs(float(line) * 2 - round(float(line) * 2)) < 1e-9


def _track(key: str, odd: float) -> dict:
    now=time.time(); q=_HISTORY[key]
    while q and now-q[0][0] > _TTL: q.popleft()
    if not q or abs(q[-1][1]-odd) > 1e-6 or now-q[-1][0] >= 20: q.append((now,float(odd)))
    if len(q)<2:return {"direction":"flat","from":round(odd,3),"to":round(odd,3),"drop_pct":0.0}
    old=float(q[0][1]); new=float(q[-1][1]); drop=(old-new)/old*100 if old>1 else 0.0
    return {"direction":"toward" if drop>0.5 else "against" if drop<-0.5 else "flat","from":round(old,3),"to":round(new,3),"drop_pct":round(drop,2)}


def _target_with_multi(entries,m,p):
    rows=_orig_target(entries,m,p)
    if not rows:return rows
    try:krows=get_live_goal_totals(m.home,m.away)
    except Exception:krows=[]
    kby={float(x.get("line")):x for x in krows if x.get("scope")=="FULL_TIME" and _standard(float(x.get("line",-99))) and lc._sane_price(x)}
    for r in rows:
        try:line=float(r.get("line")); base=float(r.get("odd"))
        except Exception:continue
        if not _standard(line):continue
        sources=[{"source":str(r.get("source") or "LSApp/Bovada"),"odd":base}]
        kr=kby.get(line)
        if kr:
            ko=float(kr["odd"]); sources.append({"source":"Kambi/BetRivers","odd":ko})
        moves=[]
        for s in sources:
            key=f"{m.event_id}|{line:g}|{s['source']}"; mv=_track(key,float(s['odd'])); s["movement"]=mv; moves.append(mv)
        r["source_prices"]=sources
        r["source_count"]=len(sources)
        if len(sources)>=2:
            vals=[float(s["odd"]) for s in sources]
            spread=(max(vals)-min(vals))/min(vals)*100 if min(vals)>0 else 999
            r["market_consensus"]="CONFIRMED" if spread<=12 else "DISAGREE"
            r["source_spread_pct"]=round(spread,2)
            r["bookmakers"]=max(int(r.get("bookmakers") or 1),len(sources))
        else:r["market_consensus"]="SINGLE_SOURCE"
        toward=sum(1 for x in moves if x.get("direction")=="toward")
        against=sum(1 for x in moves if x.get("direction")=="against")
        r["external_market_status"]="STEAM" if len(moves)>=2 and toward>=2 else "CONFLICT" if against>toward else "EARLY"
    return rows

lc._target_goal_markets=_target_with_multi
