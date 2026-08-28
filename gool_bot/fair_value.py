"""Dependency-free fair-value math for GOOL BEST BET."""
from __future__ import annotations
import math

def _f(v,d=None):
 try:return float(v)
 except Exception:return d

def implied_prob(odd):
 o=_f(odd);return None if not o or o<=1.0 else 1.0/o

def devig(probs):
 vals=[max(0.0,float(x or 0)) for x in probs];s=sum(vals);return [x/s for x in vals] if s>0 else [0.0 for _ in vals]

def devig_odds(odds):return devig([implied_prob(x) or 0.0 for x in odds])
def two_way_fair(a,b):
 p=devig_odds([a,b]);return (p[0],p[1]) if len(p)==2 and all(x>0 for x in p) else (None,None)
def expected_value(p,o):
 p=_f(p);o=_f(o);return None if p is None or o is None else p*o-1.0

def poisson_probs(lam,max_goals=8):
 lam=max(.05,min(6.,float(lam or 0)));out=[math.exp(-lam)]
 for k in range(1,max_goals+1):out.append(out[-1]*lam/k)
 out[-1]+=max(0.,1.-sum(out));return out

def score_matrix(h,a,max_goals=8):
 hp=poisson_probs(h,max_goals);ap=poisson_probs(a,max_goals);return [[x*y for y in ap] for x in hp]
def matrix_market_probs(matrix):
 btts=0.;totals={x:0. for x in (.5,1.5,2.5,3.5,4.5,5.5)};ht={x:0. for x in (.5,1.5,2.5,3.5)};at=dict(ht)
 for h,row in enumerate(matrix):
  for a,p in enumerate(row):
   if h>0 and a>0:btts+=p
   for x in totals:
    if h+a>x:totals[x]+=p
   for x in ht:
    if h>x:ht[x]+=p
    if a>x:at[x]+=p
 return {'BTTS_YES':btts,'BTTS_NO':1-btts,'TOTAL_OVER':totals,'TOTAL_UNDER':{k:1-v for k,v in totals.items()},'TEAM_HOME_OVER':ht,'TEAM_HOME_UNDER':{k:1-v for k,v in ht.items()},'TEAM_AWAY_OVER':at,'TEAM_AWAY_UNDER':{k:1-v for k,v in at.items()}}
def live_lambdas(match,stats,base_total=2.65):
 minute=max(1,min(90,int(getattr(match,'minute',0) or 1)));rem=max(3,94-minute)
 def pair(k):
  try:a,b=stats.get(k,(0,0));return float(a or 0),float(b or 0)
  except Exception:return 0.,0.
 xh,xa=pair('xg');sh,sa=pair('shots_on_target');bh,ba=pair('big_chances');ih,ia=pair('shots_inside_box');elapsed=max(8,minute);base=base_total/90.
 def side(xg,sot,big,ibox):return max(.05,min(3.2,(base*.5+(xg*.55+sot*.10+big*.18+ibox*.025)/elapsed*.5)*rem))
 return side(xh,sh,bh,ih),side(xa,sa,ba,ia)
def model_probability(row,match,stats):
 hl,al=live_lambdas(match,stats);m=matrix_market_probs(score_matrix(hl,al));kind=str(row.get('market_type') or row.get('market') or '').upper();sel=str(row.get('selection') or '').upper();line=_f(row.get('line'));hs=int(getattr(match,'home_score',0) or 0);as_=int(getattr(match,'away_score',0) or 0)
 if kind in {'TOTAL','TOTAL_OVER','OVER_UNDER','OVER','TOTAL_UNDER','UNDER'} and line is not None:
  needed=line-(hs+as_);table='TOTAL_UNDER' if kind in {'TOTAL_UNDER','UNDER'} or sel in {'UNDER','U'} else 'TOTAL_OVER';nearest=min(m[table],key=lambda x:abs(x-needed));return None if abs(nearest-needed)>.26 else m[table][nearest]
 if kind=='BTTS':
  if hs>0 and as_>0:p=1.
  elif hs>0:p=1-math.exp(-al)
  elif as_>0:p=1-math.exp(-hl)
  else:p=m['BTTS_YES']
  return p if sel not in {'NO','N'} else 1-p
 if kind in {'TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'} and line is not None:
  current=hs if kind.endswith('HOME') else as_;needed=line-current;side='HOME' if kind.endswith('HOME') else 'AWAY';under=sel in {'UNDER','U'} or 'UNDER' in str(row.get('market') or '').upper();table=f"TEAM_{side}_{'UNDER' if under else 'OVER'}";nearest=min(m[table],key=lambda x:abs(x-needed));return None if abs(nearest-needed)>.26 else m[table][nearest]
 return None
