"""GOOL LIVE auxiliary strategy framework.

Auxiliary strategies next to CORE:
1) FIRST_HALF_GOAL observes the match from kickoff and may signal at 15'-25'.
2) SECOND_HALF_OVER15 decides at half-time for Over 1.5 goals in the 2nd half.

Clock time can strengthen evidence but never create it. Evidence thresholds are
coverage-aware so leagues without xGoT/big-chance/box feeds are not made
mathematically impossible to qualify; missing metrics never count as zero-grade
failures by themselves.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
import math

CORE="core"
FIRST_HALF_GOAL="first_half_goal"
SECOND_HALF_OVER15="second_half_over15"
FIRST_MATCH_WARMUP_MINUTE=10
SECOND_HALF_WARMUP_UNTIL=55
POST_GOAL_COOLDOWN_MINUTES=5
CORE_MAX_NEW_MINUTE=75
CORE_MAX_REENTRY_MINUTE=80
FH_OBSERVE_FROM=0
FH_SIGNAL_FROM=15
FH_SIGNAL_TO=25
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
    out={k:max(0.0,round(now[k]-float(baseline.get(k,0) or 0),3)) for k in TREND_KEYS}
    # Runtime may provide original provider coverage. Preserve it if present.
    available=stats.get("_available_keys") if isinstance(stats,dict) else None
    if available:out["_available_keys"]=available
    return out

def time_weight(minute:int,engine:str)->float:
    minute=int(minute or 0)
    if engine==FIRST_HALF_GOAL:progress=max(0.0,min(1.0,(minute-FH_OBSERVE_FROM)/max(1,FH_SIGNAL_TO-FH_OBSERVE_FROM)))
    elif engine==SECOND_HALF_OVER15:progress=1.0
    else:progress=max(0.0,min(1.0,minute/90.0))
    return 1.0+0.18*progress

def trend_score(d:Mapping[str,float],minute:int=0,engine:str=CORE)->float:
    raw=(float(d.get("xg",0))*36+float(d.get("xgot",0))*22+float(d.get("shots",0))*4.5+float(d.get("shots_on_target",0))*11+float(d.get("big_chances",0))*18+float(d.get("corners",0))*2.5+float(d.get("shots_inside_box",0))*3+float(d.get("touches_box",0))*.85)
    return round(max(0.0,min(100.0,raw*time_weight(minute,engine))),1)

def cooldown_ready(current_minute:int,last_goal_minute:int|None)->bool:return last_goal_minute is None or int(current_minute)-int(last_goal_minute)>=POST_GOAL_COOLDOWN_MINUTES

def core_window(minute:int,is_halftime:bool=False)->bool:
    minute=int(minute or 0);return not is_halftime and minute>=FIRST_MATCH_WARMUP_MINUTE and not (46<=minute<SECOND_HALF_WARMUP_UNTIL) and minute<=CORE_MAX_NEW_MINUTE

def _adjust(base,timing_bonus):return round(max(0,min(100,float(base)+float(timing_bonus or 0))),1)

def _coverage_keys(stats:Mapping)->set[str]:
    raw=stats.get("_available_keys") if isinstance(stats,Mapping) else None
    if isinstance(raw,(list,tuple,set)):return {str(x) for x in raw}
    # For cumulative provider stats, key presence is reliable. For deltas, the
    # runtime injects _available_keys so a legitimate zero is still available.
    return {k for k in TREND_KEYS if k in stats}

def _adaptive_evidence(stats:Mapping,checks:list[tuple[str,bool]],min_floor:int=2,ratio:float=.5):
    available=_coverage_keys(stats)
    usable=[(k,ok) for k,ok in checks if k in available]
    if not usable:
        # Old state/runtime compatibility: use non-zero/basic fields only.
        usable=[(k,ok) for k,ok in checks if float(stats.get(k,0) or 0)>0]
    passed=sum(bool(ok) for _,ok in usable);n=len(usable)
    needed=min(n,max(min_floor,int(math.ceil(n*ratio)))) if n else 99
    return passed,needed,n

def first_half_goal(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
    minute=int(minute or 0);score=_adjust(trend_score(d,minute,FIRST_HALF_GOAL),timing_bonus)
    if minute<FH_SIGNAL_FROM:return EngineDecision(FIRST_HALF_GOAL,False,score,"collecting from kickoff")
    if minute>FH_SIGNAL_TO:return EngineDecision(FIRST_HALF_GOAL,False,score,"first-half entry window closed at 25'")
    if not cooldown_ready(minute,last_goal_minute):return EngineDecision(FIRST_HALF_GOAL,False,score,"post-goal cooldown")
    checks=[
        ("xg",float(d.get("xg",0))>=.18),("xgot",float(d.get("xgot",0))>=.15),
        ("shots",float(d.get("shots",0))>=2),("shots_on_target",float(d.get("shots_on_target",0))>=1),
        ("big_chances",float(d.get("big_chances",0))>=1),("touches_box",float(d.get("touches_box",0))>=5),
        ("shots_inside_box",float(d.get("shots_inside_box",0))>=2),("corners",float(d.get("corners",0))>=2),
    ]
    evidence,needed,coverage=_adaptive_evidence(d,checks,min_floor=2,ratio=.45)
    # Later in the window we demand a slightly stronger score, not an impossible
    # fixed count of advanced metrics that some leagues never publish.
    required_score=64 if minute<22 else 66
    ok=score>=required_score and evidence>=needed
    return EngineDecision(FIRST_HALF_GOAL,ok,score,f"kickoff trend evidence={evidence}/{needed}; coverage={coverage}; score_req={required_score}; time_weight={time_weight(minute,FIRST_HALF_GOAL):.3f}; timing={float(timing_bonus or 0):+.1f}")

def second_half_over15(stats:Mapping[str,object],timing_bonus:float=0)->EngineDecision:
    xg=_total(stats,"xg");xgot=_total(stats,"xgot");shots=_total(stats,"shots");sot=_total(stats,"shots_on_target");big=_total(stats,"big_chances");inside=_total(stats,"shots_inside_box");touches=_total(stats,"touches_box");corners=_total(stats,"corners")
    raw=xg*20+xgot*14+shots*1.35+sot*4.5+big*8+inside*1.2+touches*.28+corners*.8;score=_adjust(min(100.0,raw),timing_bonus)
    # Attach provider coverage for adaptive evidence. xG proxy counts as available
    # when present; xGoT/big/box metrics that the feed does not expose do not make
    # the strategy impossible by construction.
    work=dict(stats);work["_available_keys"]=[k for k in TREND_KEYS if k in stats]
    checks=[("xg",xg>=1.15),("xgot",xgot>=.85),("shots",shots>=12),("shots_on_target",sot>=4),("big_chances",big>=2),("shots_inside_box",inside>=6),("touches_box",touches>=20),("corners",corners>=4)]
    evidence,needed,coverage=_adaptive_evidence(work,checks,min_floor=2,ratio=.5)
    return EngineDecision(SECOND_HALF_OVER15,score>=70 and evidence>=needed,score,f"1H evidence={evidence}/{needed}; coverage={coverage}; xG={xg:.2f}; SOT={sot:.0f}; timing={float(timing_bonus or 0):+.1f}")
