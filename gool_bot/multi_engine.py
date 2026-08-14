"""GOOL MULTI-ENGINE shared trend framework.

The existing CORE engine remains authoritative. HT_HUNTER and LATE_RISK are
independent one-shot engines and can be enabled after shadow validation.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

CORE="core"
HT_HUNTER="first_half"
LATE_RISK="second_half"

FIRST_MATCH_WARMUP_MINUTE=10
SECOND_HALF_WARMUP_UNTIL=55
POST_GOAL_COOLDOWN_MINUTES=5
CORE_MAX_NEW_MINUTE=75
CORE_MAX_REENTRY_MINUTE=80
HT_OBSERVE_FROM=30
HT_SIGNAL_FROM=35
HT_SIGNAL_TO=45
LATE_OBSERVE_FROM=70
LATE_SIGNAL_FROM=80
LATE_SIGNAL_TO=90

TREND_KEYS=("xg","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")

@dataclass(frozen=True)
class EngineDecision:
    engine:str
    eligible:bool
    score:float
    reason:str

def _total(stats:Mapping,key:str)->float:
    try:a,b=stats.get(key,(0,0));return float(a)+float(b)
    except Exception:return 0.0

def snapshot(stats:Mapping)->dict[str,float]:
    return {k:round(_total(stats,k),3) for k in TREND_KEYS}

def delta(stats:Mapping,baseline:Mapping|None)->dict[str,float]:
    now=snapshot(stats);baseline=baseline or {}
    return {k:max(0.0,round(now[k]-float(baseline.get(k,0) or 0),3)) for k in TREND_KEYS}

def trend_score(d:Mapping[str,float])->float:
    """Fresh pressure only; accumulated match totals do not inflate this score."""
    raw=(float(d.get("xg",0))*38 + float(d.get("shots",0))*5 +
         float(d.get("shots_on_target",0))*12 + float(d.get("big_chances",0))*18 +
         float(d.get("corners",0))*3 + float(d.get("shots_inside_box",0))*3 +
         float(d.get("touches_box",0))*0.9)
    return round(max(0.0,min(100.0,raw)),1)

def cooldown_ready(current_minute:int,last_goal_minute:int|None)->bool:
    if last_goal_minute is None:return True
    return int(current_minute)-int(last_goal_minute)>=POST_GOAL_COOLDOWN_MINUTES

def core_window(minute:int,is_halftime:bool=False)->bool:
    minute=int(minute or 0)
    if is_halftime:return False
    if minute<FIRST_MATCH_WARMUP_MINUTE:return False
    if 46<=minute<SECOND_HALF_WARMUP_UNTIL:return False
    return minute<=CORE_MAX_NEW_MINUTE

def ht_hunter(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None)->EngineDecision:
    minute=int(minute or 0);score=trend_score(d)
    if minute<HT_SIGNAL_FROM:return EngineDecision(HT_HUNTER,False,score,"collecting first-half trend")
    if minute>HT_SIGNAL_TO:return EngineDecision(HT_HUNTER,False,score,"first-half window closed")
    if not cooldown_ready(minute,last_goal_minute):return EngineDecision(HT_HUNTER,False,score,"5-minute post-goal cooldown")
    # one-shot engine: caller must also enforce one signal_id per event/engine
    evidence=sum((d.get("xg",0)>=.25,d.get("shots",0)>=3,d.get("shots_on_target",0)>=1,d.get("big_chances",0)>=1,d.get("touches_box",0)>=6))
    return EngineDecision(HT_HUNTER,score>=68 and evidence>=2,score,f"fresh evidence={evidence}")

def late_risk(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None)->EngineDecision:
    minute=int(minute or 0);score=trend_score(d)
    if minute<LATE_SIGNAL_FROM:return EngineDecision(LATE_RISK,False,score,"collecting late trend")
    if minute>LATE_SIGNAL_TO:return EngineDecision(LATE_RISK,False,score,"match window closed")
    if not cooldown_ready(minute,last_goal_minute):return EngineDecision(LATE_RISK,False,score,"5-minute post-goal cooldown")
    evidence=sum((d.get("xg",0)>=.28,d.get("shots",0)>=3,d.get("shots_on_target",0)>=1,d.get("big_chances",0)>=1,d.get("shots_inside_box",0)>=2,d.get("touches_box",0)>=7))
    # Higher threshold because this is explicitly a high-price/high-variance system.
    return EngineDecision(LATE_RISK,score>=78 and evidence>=3,score,f"fresh evidence={evidence}")
