"""Bounded pre-match/competition prior for the LIVE engine.

The prior may strengthen/weaken an existing LIVE setup, but may not manufacture a
signal on its own. It separates recent form, venue-specific form, H2H and league
profile (same-competition scoring level + competition type).
"""
from __future__ import annotations
import logging,re,time
import live_candidate_patch as lc
from match_history import fetch_match_history
from league_profile import build_profile,to_dict
logger=logging.getLogger("context_adjustment")
_orig=lc._evaluate
_CACHE={};TTL=900


def _norm(s):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).split())
def _team_eq(a,b):
    a=_norm(a);b=_norm(b);return bool(a and b and (a in b or b in a))
def _avg(rows):return sum(r.total for r in rows)/len(rows) if rows else None
def _over25(rows):return sum(r.total>=3 for r in rows)/len(rows) if rows else None

def _ctx(m):
    now=time.time();c=_CACHE.get(m.event_id)
    if c and now-c[0]<TTL:return c[1]
    try:h=fetch_match_history(m.event_id,m.home,m.away,limit=10)
    except Exception:return {}
    home_venue=[r for r in h.home_recent if _team_eq(r.home,m.home)]
    away_venue=[r for r in h.away_recent if _team_eq(r.away,m.away)]
    league_n=_norm(m.league)
    same_comp=[r for r in (h.home_recent+h.away_recent+h.h2h) if league_n and (_norm(r.competition) in league_n or league_n in _norm(r.competition))]
    profile=build_profile(m.league,same_comp)
    data={
      "home_recent_avg":_avg(h.home_recent),"away_recent_avg":_avg(h.away_recent),
      "home_venue_avg":_avg(home_venue),"away_venue_avg":_avg(away_venue),
      "h2h_avg":_avg(h.h2h),"league_avg":_avg(same_comp),
      "home_venue_o25":_over25(home_venue),"away_venue_o25":_over25(away_venue),
      "h2h_o25":_over25(h.h2h),"league_n":len(same_comp),
      "league_profile":to_dict(profile),
    }
    _CACHE[m.event_id]=(now,data);return data

def _score(data):
    vals=[]
    for k,w in (("home_venue_avg",1.35),("away_venue_avg",1.35),("h2h_avg",.8),("home_recent_avg",.6),("away_recent_avg",.6)):
        v=data.get(k)
        if v is not None:vals.append((float(v),w))
    if vals:
        form_avg=sum(v*w for v,w in vals)/sum(w for _,w in vals)
        form_bonus=max(-4.0,min(4.0,(form_avg-2.65)*3.0))
    else:form_bonus=0.0
    lp=data.get("league_profile") or {};rate=float(lp.get("goal_rate_multiplier",1.0) or 1.0);rel=float(lp.get("reliability",.5) or .5)
    league_bonus=max(-3.5,min(3.5,(rate-1.0)*18.0))*rel
    bonus=max(-6.0,min(6.0,form_bonus+league_bonus))
    return max(0.0,min(100.0,50.0+bonus*7.0)),bonus

def _rescale_probability(pct,mult):
    try:p=max(0.0,min(.999,float(pct)/100.0));m=max(.70,min(1.35,float(mult)));return round((1-(1-p)**m)*100,1)
    except Exception:return pct

def _evaluate(m,s,p,goals,market):
    qualifies,route,master,scores,hz,market=_orig(m,s,p,goals,market)
    data=_ctx(m);prior,bonus=_score(data)
    lp=data.get("league_profile") or {}
    scores["PREMATCH_CONTEXT"]=round(prior,1)
    scores["LEAGUE_CONTEXT"]=round(50.0+max(-35,min(35,(float(lp.get("goal_rate_multiplier",1))-1)*140)),1)
    original_master=float(master);master=max(0.0,min(100.0,original_master+bonus))
    # Apply competition scoring tempo to actual goal hazard, not only to MASTER.
    if hz:
        phase_mult=float(lp.get("first_half_multiplier",1.0) if int(getattr(m,"minute",0) or 0)<=45 else lp.get("late_multiplier",1.0) if int(getattr(m,"minute",0) or 0)>=70 else lp.get("goal_rate_multiplier",1.0))
        rel=float(lp.get("reliability",.5) or .5);effective=1.0+(phase_mult-1.0)*rel
        hz=tuple(_rescale_probability(x,effective) for x in hz)
        market["league_hazard_multiplier"]=round(effective,3)
    # Context can veto marginal setups; it cannot create a signal on its own.
    if bonus<=-4.0 and original_master<75:qualifies=False;route="REJECT_CONTEXT"
    market["context_bonus"]=round(bonus,2);market["context"]={k:v for k,v in data.items() if v is not None}
    market["league_profile"]=lp
    return qualifies,route,round(master,1),scores,hz,market

lc._evaluate=_evaluate
