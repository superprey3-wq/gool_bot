"""GOOL CORE V3: bidirectional remaining-goals distribution.

The model does not assume that a live match must produce another goal.  It
estimates a state-conditioned remaining-goals mean and derives OVER/UNDER/NO BET
views for FULL_TIME, FIRST_HALF and SECOND_HALF.
"""
from __future__ import annotations
import math
from dataclasses import dataclass,asdict
from typing import Mapping

TREND=("xg","xgot","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")

@dataclass(frozen=True)
class DistributionDecision:
 period:str
 minute:int
 current_goals:int
 minutes_left:float
 potential:float
 threat:float
 lambda_remaining:float
 p0:float
 p1:float
 p2plus:float
 p_goal_10m:float
 p_any_goal:float
 direction:str
 line:float|None
 probability:float
 fair_odd:float|None
 confidence:float
 reason:str
 def dict(self):return asdict(self)

def _total(stats:Mapping,key:str)->float:
 try:a,b=stats.get(key,(0,0));return max(0.0,float(a)+float(b))
 except Exception:return 0.0

def _delta(stats:Mapping,previous:Mapping|None,key:str)->float:
 if not previous:return 0.0
 return max(0.0,_total(stats,key)-_total(previous,key))

def _clip(v,lo=0.0,hi=100.0):return max(lo,min(hi,float(v)))
def _pois(k,lam):return math.exp(-lam)*(lam**k)/math.factorial(k)

def _potential(stats:Mapping)->float:
 xg=_total(stats,"xg");xgot=_total(stats,"xgot");shots=_total(stats,"shots");sot=_total(stats,"shots_on_target");big=_total(stats,"big_chances");inside=_total(stats,"shots_inside_box");touches=_total(stats,"touches_box");corners=_total(stats,"corners")
 return round(_clip(xg*20+xgot*11+shots*1.15+sot*4.8+big*8.5+inside*1.15+touches*.20+corners*.55),1)

def _threat(stats:Mapping,previous:Mapping|None)->tuple[float,int,dict]:
 if not previous:return 0.0,0,{}
 d={k:_delta(stats,previous,k) for k in TREND}
 raw=d["xg"]*42+d["xgot"]*22+d["shots"]*4.2+d["shots_on_target"]*12+d["big_chances"]*18+d["shots_inside_box"]*3.2+d["touches_box"]*.85+d["corners"]*2.5
 confirmations=sum((d["xg"]>=.15,d["shots_on_target"]>=1,d["shots"]>=3,d["big_chances"]>=1,d["shots_inside_box"]>=2,d["touches_box"]>=6,d["corners"]>=2))
 return round(_clip(raw),1),int(confirmations),d

def evaluate(period:str,minute:int,current_goals:int,stats:Mapping,previous:Mapping|None,score_margin:int=0,period_start_minute:int=0,period_end_minute:int=94)->DistributionDecision:
 minute=max(0,int(minute or 0));current_goals=max(0,int(current_goals or 0));left=max(0.0,float(period_end_minute-minute));potential=_potential(stats);threat,confirm,d=_threat(stats,previous)
 base_rate=2.70/94.0
 live_mult=.58+potential/170.0+threat/145.0
 if previous is None:live_mult=min(live_mult,1.05)
 if abs(int(score_margin))==1:live_mult*=1.04
 elif abs(int(score_margin))>=2 and minute>=55:live_mult*=.88
 if minute>=82:live_mult*=.90
 lam=max(.01,min(3.8,base_rate*left*live_mult))
 p0=_pois(0,lam);p1=_pois(1,lam);p2=max(0.0,1-p0-p1);pany=1-p0
 lam10=max(.001,lam*min(10.0,left)/max(left,1.0));p10=1-math.exp(-lam10)
 line=float(current_goals)+.5
 pover=pany;punder=p0
 direction="NO_BET";prob=max(pover,punder);chosen=None

 # Production gate: strong probability plus matching live football evidence.
 # The previous 68%/70-threat combination was so restrictive that valid states
 # almost never reached delivery.  Keep selectivity, but remove starvation.
 over_prob_gate=.64
 under_prob_gate=.64
 if previous is not None:
  if pover>=over_prob_gate and threat>=55 and potential>=48 and confirm>=2:
   direction="OVER";prob=pover;chosen=line
  elif punder>=under_prob_gate and threat<=35 and potential<=55 and confirm<=1:
   direction="UNDER";prob=punder;chosen=line

 confidence=_clip(abs(prob-.5)*200)
 fair=(1.0/prob) if direction!="NO_BET" and prob>0 else None
 reason=(f"confirm={confirm}; dxG={d.get('xg',0):.2f}; dSOT={d.get('shots_on_target',0):.0f}; "
         f"potential={potential:.1f}; threat={threat:.1f}; pAny={pany*100:.1f}; p0={p0*100:.1f}")
 return DistributionDecision(period,minute,current_goals,round(left,1),potential,threat,round(lam,3),round(p0*100,1),round(p1*100,1),round(p2*100,1),round(p10*100,1),round(pany*100,1),direction,chosen,round(prob*100,1),round(fair,2) if fair else None,round(confidence,1),reason)
