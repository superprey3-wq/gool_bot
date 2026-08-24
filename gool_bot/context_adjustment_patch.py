"""Bounded pre-match/competition prior for the LIVE engine.

The prior may strengthen/weaken an existing LIVE setup, but may not manufacture a
signal on its own. It separates recent form, venue-specific form, H2H and matches
from the same competition when available.
"""
from __future__ import annotations
import logging,re,time
import live_candidate_patch as lc
from match_history import fetch_match_history
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
    try:h=fetch_match_history(m.event_id,m.home,m.away,limit=8)
    except Exception:return {}
    home_venue=[r for r in h.home_recent if _team_eq(r.home,m.home)]
    away_venue=[r for r in h.away_recent if _team_eq(r.away,m.away)]
    league_n=_norm(m.league)
    same_comp=[r for r in (h.home_recent+h.away_recent) if league_n and (_norm(r.competition) in league_n or league_n in _norm(r.competition))]
    data={
      "home_recent_avg":_avg(h.home_recent),"away_recent_avg":_avg(h.away_recent),
      "home_venue_avg":_avg(home_venue),"away_venue_avg":_avg(away_venue),
      "h2h_avg":_avg(h.h2h),"league_avg":_avg(same_comp),
      "home_venue_o25":_over25(home_venue),"away_venue_o25":_over25(away_venue),
      "h2h_o25":_over25(h.h2h),"league_n":len(same_comp),
    }
    _CACHE[m.event_id]=(now,data);return data

def _score(data):
    vals=[]
    for k,w in (("home_venue_avg",1.35),("away_venue_avg",1.35),("h2h_avg",.8),("league_avg",1.15),("home_recent_avg",.6),("away_recent_avg",.6)):
        v=data.get(k)
        if v is not None:vals.append((float(v),w))
    if not vals:return 50.0,0.0
    avg=sum(v*w for v,w in vals)/sum(w for _,w in vals)
    # Neutral around 2.65 total goals; bounded to +/-6 master points.
    bonus=max(-6.0,min(6.0,(avg-2.65)*4.0))
    return max(0.0,min(100.0,50.0+bonus*7.0)),bonus

def _competition_uncertainty(league):
    s=_norm(league)
    if any(x in s for x in ("friendly","friendlies","cup","play off","playoff","qualification")):return .65
    if any(x in s for x in ("u19","u20","u21","youth","women")):return .80
    return 1.0

def _evaluate(m,s,p,goals,market):
    qualifies,route,master,scores,hz,market=_orig(m,s,p,goals,market)
    data=_ctx(m);prior,bonus=_score(data);bonus*=_competition_uncertainty(m.league)
    scores["PREMATCH_CONTEXT"]=round(prior,1)
    scores["LEAGUE_CONTEXT"]=round(50.0+max(-35,min(35,bonus*6)),1)
    original_master=float(master);master=max(0.0,min(100.0,original_master+bonus))
    # Historical context can veto a marginal setup but can never create one alone.
    if bonus<=-4.0 and original_master<75:qualifies=False;route="REJECT_CONTEXT"
    market["context_bonus"]=round(bonus,2);market["context"]={k:v for k,v in data.items() if v is not None}
    return qualifies,route,round(master,1),scores,hz,market

lc._evaluate=_evaluate
