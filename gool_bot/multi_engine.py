"""GOOL LIVE auxiliary strategy framework.

Auxiliary strategies next to CORE:
1) FIRST_HALF_GOAL observes the match from kickoff and may signal at 15'-25'.
2) SECOND_HALF_OVER15 decides at half-time for Over 1.5 goals in the 2nd half.

Clock time can strengthen evidence but never create it. Auxiliary engines require
at least 80/100 before the runtime applies the separate 75% next-goal probability gate.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
CORE="core";FIRST_HALF_GOAL="first_half_goal";SECOND_HALF_OVER15="second_half_over15"
FIRST_MATCH_WARMUP_MINUTE=10;SECOND_HALF_WARMUP_UNTIL=55;POST_GOAL_COOLDOWN_MINUTES=5;CORE_MAX_NEW_MINUTE=75;CORE_MAX_REENTRY_MINUTE=80;FH_OBSERVE_FROM=0;FH_SIGNAL_FROM=15;FH_SIGNAL_TO=25;HALFTIME_MINUTE=45
TREND_KEYS=("xg","xgot","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")
@dataclass(frozen=True)
class EngineDecision:engine:str;eligible:bool;score:float;reason:str
def _total(stats:Mapping,key:str)->float:
 try:a,b=stats.get(key,(0,0));return float(a)+float(b)
 except Exception:return 0.0
def _sides(stats:Mapping,key:str)->tuple[float,float]:
 try:a,b=stats.get(key,(0,0));return float(a),float(b)
 except Exception:return 0.0,0.0
def snapshot(stats:Mapping)->dict[str,float]:return {k:round(_total(stats,k),3) for k in TREND_KEYS}
def delta(stats:Mapping,baseline:Mapping|None)->dict[str,float]:
 now=snapshot(stats);baseline=baseline or {};return {k:max(0.0,round(now[k]-float(baseline.get(k,0) or 0),3)) for k in TREND_KEYS}
def time_weight(minute:int,engine:str)->float:
 minute=int(minute or 0)
 if engine==FIRST_HALF_GOAL:progress=max(0.0,min(1.0,(minute-FH_OBSERVE_FROM)/max(1,FH_SIGNAL_TO-FH_OBSERVE_FROM)))
 elif engine==SECOND_HALF_OVER15:progress=1.0
 else:progress=max(0.0,min(1.0,minute/90.0))
 return 1.0+0.18*progress
def trend_score(d:Mapping[str,float],minute:int=0,engine:str=CORE)->float:
 raw=(float(d.get("xg",0))*40+float(d.get("xgot",0))*25+float(d.get("shots",0))*3.5+float(d.get("shots_on_target",0))*13+float(d.get("big_chances",0))*21+float(d.get("corners",0))*2+float(d.get("shots_inside_box",0))*4+float(d.get("touches_box",0))*.75);return round(max(0.0,min(100.0,raw*time_weight(minute,engine))),1)
def cooldown_ready(current_minute:int,last_goal_minute:int|None)->bool:return last_goal_minute is None or int(current_minute)-int(last_goal_minute)>=POST_GOAL_COOLDOWN_MINUTES
def core_window(minute:int,is_halftime:bool=False)->bool:
 minute=int(minute or 0);return not is_halftime and minute>=FIRST_MATCH_WARMUP_MINUTE and not (46<=minute<SECOND_HALF_WARMUP_UNTIL) and minute<=CORE_MAX_NEW_MINUTE
def _adjust(base,timing_bonus):return round(max(0,min(100,float(base)+float(timing_bonus or 0))),1)
def first_half_goal(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
 minute=int(minute or 0);score=_adjust(trend_score(d,minute,FIRST_HALF_GOAL),timing_bonus)
 if minute<FH_SIGNAL_FROM:return EngineDecision(FIRST_HALF_GOAL,False,score,"collecting from kickoff")
 if minute>FH_SIGNAL_TO:return EngineDecision(FIRST_HALF_GOAL,False,score,"first-half entry window closed at 25'")
 if not cooldown_ready(minute,last_goal_minute):return EngineDecision(FIRST_HALF_GOAL,False,score,"post-goal cooldown")
 xg=float(d.get("xg",0) or 0);xgot=float(d.get("xgot",0) or 0);shots=float(d.get("shots",0) or 0);sot=float(d.get("shots_on_target",0) or 0);big=float(d.get("big_chances",0) or 0);inside=float(d.get("shots_inside_box",0) or 0);touches=float(d.get("touches_box",0) or 0)
 quality=(xg>=.32 or xgot>=.28 or big>=1 or sot>=2);pressure=(shots>=4 and (inside>=2 or touches>=8));evidence=sum((xg>=.32,xgot>=.28,shots>=4,sot>=2,big>=1,inside>=2,touches>=8));needed=4 if minute>=22 else 3;eligible=score>=80 and quality and pressure and evidence>=needed
 return EngineDecision(FIRST_HALF_GOAL,eligible,score,f"kickoff trend quality={int(quality)} pressure={int(pressure)} evidence={evidence}/{needed}; xG={xg:.2f}; SOT={sot:.0f}; box={inside:.0f}; timing={float(timing_bonus or 0):+.1f}")
def halftime_context(stats:Mapping[str,object],home_score:int,away_score:int)->dict[str,object]:
 hxg,axg=_sides(stats,"xg");hsot,asot=_sides(stats,"shots_on_target");hbig,abig=_sides(stats,"big_chances");hbox,abox=_sides(stats,"shots_inside_box");hpower=hxg*3.2+hsot*.9+hbig*1.6+hbox*.22;apower=axg*3.2+asot*.9+abig*1.6+abox*.22;gap=hpower-apower;strong="balanced" if abs(gap)<1.1 else "home" if gap>0 else "away";margin=int(home_score)-int(away_score);bonus=0.0;tag="balanced_score"
 if margin==0:bonus=3.0;tag="draw_open"
 elif abs(margin)==1:
  leader="home" if margin>0 else "away";trailer="away" if margin>0 else "home"
  if strong==trailer:bonus=6.0;tag="stronger_team_trailing"
  elif strong==leader:bonus=.5;tag="stronger_team_leads_narrow"
  else:bonus=2.0;tag="one_goal_game"
 else:
  leader="home" if margin>0 else "away"
  if strong==leader:bonus=-8.0;tag="strong_team_comfortable_lead"
  else:bonus=-3.0;tag="two_goal_margin"
 return {"strong_side":strong,"home_power":round(hpower,2),"away_power":round(apower,2),"score_margin":margin,"bonus":bonus,"tag":tag}
def second_half_over15(stats:Mapping[str,object],timing_bonus:float=0,score_context:Mapping[str,object]|None=None)->EngineDecision:
 xg=_total(stats,"xg");xgot=_total(stats,"xgot");shots=_total(stats,"shots");sot=_total(stats,"shots_on_target");big=_total(stats,"big_chances");inside=_total(stats,"shots_inside_box");touches=_total(stats,"touches_box");corners=_total(stats,"corners");context_bonus=float((score_context or {}).get("bonus",0) or 0);raw=xg*23+xgot*16+shots*1.1+sot*5.5+big*10+inside*1.5+touches*.25+corners*.6;score=_adjust(min(100.0,raw),float(timing_bonus or 0)+context_bonus);quality=(xg>=1.35 or xgot>=1.05 or big>=3) and sot>=4;pressure=shots>=13 and inside>=7 and touches>=22;evidence=sum((xg>=1.35,xgot>=1.05,shots>=13,sot>=5,big>=2,inside>=7,touches>=22,corners>=5));tag=str((score_context or {}).get("tag") or "no_score_context");stricter=tag=="strong_team_comfortable_lead";eligible=score>=(84 if stricter else 80) and quality and pressure and evidence>=(6 if stricter else 5)
 return EngineDecision(SECOND_HALF_OVER15,eligible,score,f"1H quality={int(quality)} pressure={int(pressure)} evidence={evidence}/{6 if stricter else 5}; xG={xg:.2f}; xGOT={xgot:.2f}; SOT={sot:.0f}; big={big:.0f}; box={inside:.0f}; timing={float(timing_bonus or 0):+.1f}; score_ctx={tag} {context_bonus:+.1f}")
