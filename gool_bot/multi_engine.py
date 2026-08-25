"""GOOL LIVE auxiliary strategy framework.

Two auxiliary strategies sit next to CORE:
1) FIRST_HALF_GOAL: one more goal in the first half, entry window 15'-20'.
2) SECOND_HALF_OVER15: Over 1.5 goals in the second half, decision at half-time.

Clock time can strengthen evidence but never create it.  The old LATE RISK
strategy is retired; LATE_RISK remains only as a compatibility alias.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

CORE="core"
FIRST_HALF_GOAL="first_half_goal"
SECOND_HALF_OVER15="second_half_over15"
# Backward-compatible aliases for old imports/state. No late-risk logic remains.
HT_HUNTER=FIRST_HALF_GOAL
LATE_RISK=SECOND_HALF_OVER15

FIRST_MATCH_WARMUP_MINUTE=10
SECOND_HALF_WARMUP_UNTIL=55
POST_GOAL_COOLDOWN_MINUTES=5
CORE_MAX_NEW_MINUTE=75
CORE_MAX_REENTRY_MINUTE=80

FH_OBSERVE_FROM=10
FH_SIGNAL_FROM=15
FH_SIGNAL_TO=20
HALFTIME_MINUTE=45
TREND_KEYS=("xg","xgot","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")

@dataclass(frozen=True)
class EngineDecision:
    engine:str;eligible:bool;score:float;reason:str

def _total(stats:Mapping,key:str)->float:
    try:a,b=stats.get(key,(0,0));return float(a)+float(b)
    except Exception:return 0.0

def snapshot(stats:Mapping)->dict[str,float]:return {k:round(_total(stats,k),3) for k in TREND_KEYS}

def delta(stats:Mapping,baseline:Mapping|None)->dict[str,float]:
    now=snapshot(stats);baseline=baseline or {}
    return {k:max(0.0,round(now[k]-float(baseline.get(k,0) or 0),3)) for k in TREND_KEYS}

def time_weight(minute:int,engine:str)->float:
    minute=int(minute or 0)
    if engine==FIRST_HALF_GOAL:
        progress=max(0.0,min(1.0,(minute-FH_OBSERVE_FROM)/max(1,FH_SIGNAL_TO-FH_OBSERVE_FROM)))
    elif engine==SECOND_HALF_OVER15:
        progress=1.0
    else:
        progress=max(0.0,min(1.0,minute/90.0))
    return 1.0+0.18*progress

def trend_score(d:Mapping[str,float],minute:int=0,engine:str=CORE)->float:
    raw=(float(d.get("xg",0))*36+float(d.get("xgot",0))*22+float(d.get("shots",0))*4.5+
         float(d.get("shots_on_target",0))*11+float(d.get("big_chances",0))*18+
         float(d.get("corners",0))*2.5+float(d.get("shots_inside_box",0))*3+
         float(d.get("touches_box",0))*.85)
    return round(max(0.0,min(100.0,raw*time_weight(minute,engine))),1)

def cooldown_ready(current_minute:int,last_goal_minute:int|None)->bool:return last_goal_minute is None or int(current_minute)-int(last_goal_minute)>=POST_GOAL_COOLDOWN_MINUTES

def core_window(minute:int,is_halftime:bool=False)->bool:
    minute=int(minute or 0);return not is_halftime and minute>=FIRST_MATCH_WARMUP_MINUTE and not (46<=minute<SECOND_HALF_WARMUP_UNTIL) and minute<=CORE_MAX_NEW_MINUTE

def _adjust(base,timing_bonus):return round(max(0,min(100,float(base)+float(timing_bonus or 0))),1)

def first_half_goal(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
    minute=int(minute or 0);raw=trend_score(d,minute,FIRST_HALF_GOAL);score=_adjust(raw,timing_bonus)
    if minute<FH_SIGNAL_FROM:return EngineDecision(FIRST_HALF_GOAL,False,score,"collecting 1H trend")
    if minute>FH_SIGNAL_TO:return EngineDecision(FIRST_HALF_GOAL,False,score,"1H entry window closed at 20'")
    if not cooldown_ready(minute,last_goal_minute):return EngineDecision(FIRST_HALF_GOAL,False,score,"post-goal cooldown")
    evidence=sum((d.get("xg",0)>=.18,d.get("xgot",0)>=.15,d.get("shots",0)>=2,d.get("shots_on_target",0)>=1,d.get("big_chances",0)>=1,d.get("touches_box",0)>=5))
    return EngineDecision(FIRST_HALF_GOAL,score>=64 and evidence>=2,score,f"fresh evidence={evidence}; time_weight={time_weight(minute,FIRST_HALF_GOAL):.3f}; timing={float(timing_bonus or 0):+.1f}")

def second_half_over15(stats:Mapping[str,object],timing_bonus:float=0)->EngineDecision:
    """Half-time decision for Over 1.5 goals in the second half.

    Uses full first-half evidence because the market is selected during the break.
    It intentionally requires a broad attacking profile rather than one isolated stat.
    """
    xg=_total(stats,"xg");xgot=_total(stats,"xgot");shots=_total(stats,"shots");sot=_total(stats,"shots_on_target");big=_total(stats,"big_chances");inside=_total(stats,"shots_inside_box");touches=_total(stats,"touches_box");corners=_total(stats,"corners")
    raw=(xg*20+xgot*14+shots*1.35+sot*4.5+big*8+inside*1.2+touches*.28+corners*.8)
    score=_adjust(min(100.0,raw),timing_bonus)
    evidence=sum((xg>=1.15,xgot>=.85,shots>=12,sot>=4,big>=2,inside>=6,touches>=20,corners>=4))
    return EngineDecision(SECOND_HALF_OVER15,score>=70 and evidence>=4,score,f"1H evidence={evidence}; xG={xg:.2f}; SOT={sot:.0f}; timing={float(timing_bonus or 0):+.1f}")

# Compatibility wrappers used by older imports.
def ht_hunter(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
    return first_half_goal(minute,d,last_goal_minute,timing_bonus)

def late_risk(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
    return EngineDecision(SECOND_HALF_OVER15,False,0.0,"late-risk retired; use half-time second_half_over15")
