"""Dependency-free fair-value math for GOOL BEST BET.

Small/fast by design: no numpy/scipy, no ML model loaded into RAM.  The Poisson
matrix is capped at 8 goals per side (~81 cells) and is suitable for low-memory
workers.
"""
from __future__ import annotations
import math

def _f(v,d=None):
 try:return float(v)
 except Exception:return d

def implied_prob(odd):
 o=_f(odd)
 return None if not o or o<=1.0 else 1.0/o

def devig(probs):
 vals=[max(0.0,float(x or 0)) for x in probs];s=sum(vals)
 return [x/s for x in vals] if s>0 else [0.0 for _ in vals]

def devig_odds(odds):
 raw=[implied_prob(x) or 0.0 for x in odds]
 return devig(raw)

def two_way_fair(odd_a,odd_b):
 p=devig_odds([odd_a,odd_b])
 return (p[0],p[1]) if len(p)==2 and all(x>0 for x in p) else (None,None)

def expected_value(fair_prob,odd):
 p=_f(fair_prob);o=_f(odd)
 return None if p is None or o is None else p*o-1.0

def poisson_probs(lam,max_goals=8):
 lam=max(0.05,min(6.0,float(lam or 0)));out=[];p=math.exp(-lam);out.append(p)
 for k in range(1,max_goals+1):p=p*lam/k;out.append(p)
 # Fold tiny tail into the last bucket so matrix mass remains ~1.
 tail=max(0.0,1.0-sum(out));out[-1]+=tail
 return out

def score_matrix(home_lam,away_lam,max_goals=8):
 hp=poisson_probs(home_lam,max_goals);ap=poisson_probs(away_lam,max_goals)
 return [[h*a for a in ap] for h in hp]

def matrix_market_probs(matrix):
 home=draw=away=btts=0.0;totals={x:0.0 for x in (0.5,1.5,2.5,3.5,4.5,5.5)}
 home_totals={x:0.0 for x in (0.5,1.5,2.5,3.5)};away_totals=dict(home_totals)
 for h,row in enumerate(matrix):
  for a,p in enumerate(row):
   if h>a:home+=p
   elif h==a:draw+=p
   else:away+=p
   if h>0 and a>0:btts+=p
   for line in totals:
    if h+a>line:totals[line]+=p
   for line in home_totals:
    if h>line:home_totals[line]+=p
    if a>line:away_totals[line]+=p
 return {"HOME":home,"DRAW":draw,"AWAY":away,"BTTS_YES":btts,"BTTS_NO":1-btts,"TOTAL_OVER":totals,"TOTAL_UNDER":{k:1-v for k,v in totals.items()},"TEAM_HOME_OVER":home_totals,"TEAM_HOME_UNDER":{k:1-v for k,v in home_totals.items()},"TEAM_AWAY_OVER":away_totals,"TEAM_AWAY_UNDER":{k:1-v for k,v in away_totals.items()}}

def live_lambdas(match,stats,base_total=2.65):
 """Cheap LIVE expected-goals remainder estimate from score/time/xG/SOT pressure."""
 minute=max(1,min(90,int(getattr(match,"minute",0) or 1)));rem=max(3,94-minute)
 def pair(k):
  try:a,b=stats.get(k,(0,0));return float(a or 0),float(b or 0)
  except Exception:return 0.0,0.0
 xh,xa=pair("xg");sh,sa=pair("shots_on_target");bh,ba=pair("big_chances");ih,ia=pair("shots_inside_box")
 elapsed=max(8,minute);base_rate=base_total/90.0
 def side(xg,sot,big,ibox):
  observed=(xg*.55+sot*.10+big*.18+ibox*.025)/elapsed
  rate=base_rate*.5+observed*.5
  return max(.05,min(3.2,rate*rem))
 return side(xh,sh,bh,ih),side(xa,sa,ba,ia)

def model_probability(row,match,stats):
 """Return a coherent probability for supported markets from one score matrix."""
 hl,al=live_lambdas(match,stats);m=matrix_market_probs(score_matrix(hl,al));kind=str(row.get("market_type") or row.get("market") or "").upper();sel=str(row.get("selection") or "").upper();line=_f(row.get("line"));hs=int(getattr(match,"home_score",0) or 0);as_=int(getattr(match,"away_score",0) or 0)
 # Matrix describes remaining goals. For full-time totals, shift line by current goals.
 if kind in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER","TOTAL_UNDER","UNDER"} and line is not None:
  needed=line-(hs+as_);table="TOTAL_UNDER" if kind in {"TOTAL_UNDER","UNDER"} or sel in {"UNDER","U"} else "TOTAL_OVER"
  # Map remaining threshold to nearest standard half-line. Integer/quarter lines are left to market model.
  nearest=min(m[table],key=lambda x:abs(x-needed))
  if abs(nearest-needed)>.26:return None
  return m[table][nearest]
 if kind=="BTTS":
  if hs>0 and as_>0:return 1.0 if sel not in {"NO","N"} else 0.0
  # Need the missing team to score; matrix BTTS alone is not enough after one side already scored.
  if hs>0:
   p=1-math.exp(-al)
  elif as_>0:p=1-math.exp(-hl)
  else:p=m["BTTS_YES"]
  return p if sel not in {"NO","N"} else 1-p
 if kind in {"TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and line is not None:
  current=hs if kind.endswith("HOME") else as_;needed=line-current;side="HOME" if kind.endswith("HOME") else "AWAY";under=sel in {"UNDER","U"} or "UNDER" in str(row.get("market") or "").upper();table=f"TEAM_{side}_{'UNDER' if under else 'OVER'}";nearest=min(m[table],key=lambda x:abs(x-needed))
  return None if abs(nearest-needed)>.26 else m[table][nearest]
 return None
