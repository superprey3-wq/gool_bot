"""Bounded pre-match/competition prior for the LIVE engine.

Recent form, venue form, H2H and league profile may adjust an existing LIVE
setup only modestly. Flashscore red cards are attached as explicit context; they
never manufacture a signal on their own.
"""
from __future__ import annotations
import logging,re,time
import live_candidate_patch as lc
from match_history import fetch_match_history
from league_profile import build_profile,to_dict
from red_card_stats_patch import red_cards_for_event
logger=logging.getLogger("context_adjustment");_orig=lc._evaluate;_CACHE={};TTL=900

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
 home_venue=[r for r in h.home_recent if _team_eq(r.home,m.home)];away_venue=[r for r in h.away_recent if _team_eq(r.away,m.away)];league_n=_norm(m.league);same=[r for r in (h.home_recent+h.away_recent+h.h2h) if league_n and (_norm(r.competition) in league_n or league_n in _norm(r.competition))];profile=build_profile(m.league,same)
 data={"home_recent_avg":_avg(h.home_recent),"away_recent_avg":_avg(h.away_recent),"home_venue_avg":_avg(home_venue),"away_venue_avg":_avg(away_venue),"h2h_avg":_avg(h.h2h),"league_avg":_avg(same),"home_venue_o25":_over25(home_venue),"away_venue_o25":_over25(away_venue),"h2h_o25":_over25(h.h2h),"league_n":len(same),"league_profile":to_dict(profile)};_CACHE[m.event_id]=(now,data);return data
def _score(data):
 vals=[]
 for k,w in (("home_venue_avg",1.35),("away_venue_avg",1.35),("h2h_avg",.8),("home_recent_avg",.6),("away_recent_avg",.6)):
  v=data.get(k)
  if v is not None:vals.append((float(v),w))
 form_bonus=max(-4.,min(4.,((sum(v*w for v,w in vals)/sum(w for _,w in vals))-2.65)*3.)) if vals else 0.;lp=data.get("league_profile") or {};rate=float(lp.get("goal_rate_multiplier",1.) or 1.);rel=float(lp.get("reliability",.5) or .5);league_bonus=max(-3.5,min(3.5,(rate-1.)*18.))*rel;bonus=max(-6.,min(6.,form_bonus+league_bonus));return max(0.,min(100.,50.+bonus*7.)),bonus
def _rescale(pct,mult):
 try:p=max(0.,min(.999,float(pct)/100));m=max(.70,min(1.35,float(mult)));return round((1-(1-p)**m)*100,1)
 except:return pct
def _evaluate(m,s,p,goals,market):
 qualifies,route,master,scores,hz,market=_orig(m,s,p,goals,market);data=_ctx(m);prior,bonus=_score(data);lp=data.get("league_profile") or {};scores["PREMATCH_CONTEXT"]=round(prior,1);scores["LEAGUE_CONTEXT"]=round(50.+max(-35,min(35,(float(lp.get("goal_rate_multiplier",1))-1)*140)),1);original=float(master);master=max(0.,min(100.,original+bonus))
 if hz:
  phase=float(lp.get("first_half_multiplier",1.) if int(getattr(m,"minute",0) or 0)<=45 else lp.get("late_multiplier",1.) if int(getattr(m,"minute",0) or 0)>=70 else lp.get("goal_rate_multiplier",1.));rel=float(lp.get("reliability",.5) or .5);effective=1.+(phase-1.)*rel;hz=tuple(_rescale(x,effective) for x in hz);market["league_hazard_multiplier"]=round(effective,3)
 if bonus<=-4 and original<75:qualifies=False;route="REJECT_CONTEXT"
 try:reds=red_cards_for_event(m.event_id)
 except Exception:reds=(0,0)
 market["red_cards"]={"home":int(reds[0]),"away":int(reds[1])};scores["RED_CARD_CONTEXT"]=50 if reds==(0,0) else 62
 market["context_bonus"]=round(bonus,2);market["context"]={k:v for k,v in data.items() if v is not None};market["league_profile"]=lp
 return qualifies,route,round(master,1),scores,hz,market
lc._evaluate=_evaluate
