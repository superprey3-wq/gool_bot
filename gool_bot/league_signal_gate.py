"""League/competition gate for GOOL HT HUNTER and LATE RISK.

A competition name alone never decides a bet. Same-competition evidence is
shrunk to a type prior in league_profile; this module only hard-blocks cases
where the relevant scoring window is poorly supported or demonstrably slow.
"""
from __future__ import annotations
import logging,re,time
from league_profile import build_profile,to_dict
from match_history import fetch_match_history
from multi_engine import HT_HUNTER,LATE_RISK
logger=logging.getLogger("league_signal_gate")
_CACHE={};TTL=900


def _norm(s):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).split())

def profile(match):
    now=time.time();eid=str(match.event_id);cached=_CACHE.get(eid)
    if cached and now-cached[0]<TTL:return cached[1]
    try:ctx=fetch_match_history(eid,match.home,match.away,limit=12)
    except Exception as exc:
        logger.info("LEAGUE_GATE_HISTORY_FAIL %s %s",eid,exc);ctx=None
    rows=[]
    if ctx is not None:
        league=_norm(match.league)
        for row in ctx.home_recent+ctx.away_recent+ctx.h2h:
            comp=_norm(getattr(row,"competition","") or "")
            if league and comp and (comp in league or league in comp):rows.append(row)
    p=build_profile(match.league,rows);data=to_dict(p);_CACHE[eid]=(now,data);return data


def allow(match,engine):
    p=profile(match);kind=str(p.get("kind") or "league");n=int(p.get("observed_n",0) or 0);rel=float(p.get("reliability",0) or 0)
    if engine==LATE_RISK:
        mult=float(p.get("late_multiplier",1) or 1)
        # With real same-competition evidence, a materially slow late profile is a hard veto.
        if n>=6 and mult<0.94:return False,p,f"late profile too slow ({mult:.2f}, n={n})"
        # Knockout / volatile formats need evidence before a late-goal strategy is trusted.
        if kind in {"cup","playoff","qualifier"} and n<4:return False,p,f"{kind} late profile sparse (n={n})"
        if kind in {"cup","playoff","qualifier"} and rel<0.55:return False,p,f"{kind} late reliability low ({rel:.2f})"
    elif engine==HT_HUNTER:
        mult=float(p.get("first_half_multiplier",1) or 1)
        if n>=6 and mult<0.94:return False,p,f"first-half profile too slow ({mult:.2f}, n={n})"
        if kind in {"cup","playoff","qualifier"} and n<4:return False,p,f"{kind} first-half profile sparse (n={n})"
    return True,p,"ok"


def filter_for_multi_engine(matches):
    out=[]
    for m in matches:
        minute=int(getattr(m,"minute",0) or 0)
        engine=HT_HUNTER if 35<=minute<=38 else LATE_RISK if 80<=minute<=85 else None
        if engine is None:
            out.append(m);continue
        ok,p,why=allow(m,engine)
        if ok:out.append(m)
        else:logger.info("LEAGUE_SIGNAL_REJECT %s %s - %s | %s | profile=%s",engine,getattr(m,"home",""),getattr(m,"away",""),why,p)
    return out
