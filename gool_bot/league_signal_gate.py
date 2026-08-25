"""Competition gate for GOOL auxiliary LIVE strategies.

FIRST_HALF_GOAL uses first-half scoring evidence. SECOND_HALF_OVER15 uses the
competition's second-half/late scoring evidence. Sparse cups/playoffs are treated
conservatively. League history can veto weak contexts, never create a signal.
"""
from __future__ import annotations
import logging,re,time
from league_profile import build_profile,to_dict
from match_history import fetch_match_history
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15
logger=logging.getLogger("league_signal_gate");_CACHE={};TTL=900

def _norm(s):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).split())
def profile(match):
 now=time.time();eid=str(match.event_id);cached=_CACHE.get(eid)
 if cached and now-cached[0]<TTL:return cached[1]
 try:ctx=fetch_match_history(eid,match.home,match.away,limit=12)
 except Exception as exc:logger.info("LEAGUE_GATE_HISTORY_FAIL %s %s",eid,exc);ctx=None
 rows=[]
 if ctx is not None:
  league=_norm(match.league)
  for row in ctx.home_recent+ctx.away_recent+ctx.h2h:
   comp=_norm(getattr(row,"competition","") or "")
   if league and comp and (comp in league or league in comp):rows.append(row)
 p=to_dict(build_profile(match.league,rows));_CACHE[eid]=(now,p);return p
def allow(match,engine):
 p=profile(match);kind=str(p.get("kind") or "league");recent_n=int(p.get("observed_n",0) or 0);timing_n=int(p.get("timing_matches",0) or 0);evidence=max(recent_n,timing_n);rel=float(p.get("reliability",0) or 0)
 if engine==FIRST_HALF_GOAL:
  mult=float(p.get("first_half_multiplier",1) or 1);fh=p.get("timing_first_half_gpm")
  if evidence>=20 and mult<.94:return False,p,f"first-half profile slow ({mult:.2f}, n={evidence})"
  if timing_n>=30 and fh is not None and float(fh)<.85:return False,p,f"first-half goals/match low ({float(fh):.2f})"
  if kind in {"cup","playoff","qualifier"} and evidence<8:return False,p,f"{kind} first-half sample sparse"
 elif engine==SECOND_HALF_OVER15:
  mult=float(p.get("late_multiplier",p.get("goal_rate_multiplier",1)) or 1);late=p.get("timing_late_gpm")
  if evidence>=20 and mult<.94:return False,p,f"second-half profile slow ({mult:.2f}, n={evidence})"
  if timing_n>=30 and late is not None and float(late)<.42:return False,p,f"late goals/match low ({float(late):.2f})"
  if kind in {"cup","playoff","qualifier"} and (evidence<8 or rel<.55):return False,p,f"{kind} second-half evidence weak"
 return True,p,"ok"
def filter_for_multi_engine(matches):
 out=[]
 for m in matches:
  minute=int(getattr(m,"minute",0) or 0);engine=SECOND_HALF_OVER15 if bool(getattr(m,"is_halftime",False)) else FIRST_HALF_GOAL if minute<=25 else None
  if engine is None:out.append(m);continue
  ok,p,why=allow(m,engine)
  if ok:out.append(m)
  else:logger.info("LEAGUE_SIGNAL_REJECT %s %s — %s | %s",engine,getattr(m,"home",""),getattr(m,"away",""),why)
 return out
