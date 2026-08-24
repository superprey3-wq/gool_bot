"""GOOL LIVE multi-engine trend framework.

All scores are in-play only.  Fresh attacking evidence receives a modest time
weight near the end of the relevant scoring window; the multiplier is capped so
clock time can strengthen evidence but can never manufacture it.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

CORE="core";HT_HUNTER="first_half";LATE_RISK="second_half"
FIRST_MATCH_WARMUP_MINUTE=10;SECOND_HALF_WARMUP_UNTIL=55;POST_GOAL_COOLDOWN_MINUTES=5
CORE_MAX_NEW_MINUTE=75;CORE_MAX_REENTRY_MINUTE=80
HT_OBSERVE_FROM=25;HT_SIGNAL_FROM=35;HT_SIGNAL_TO=38
LATE_OBSERVE_FROM=70;LATE_SIGNAL_FROM=80;LATE_SIGNAL_TO=85
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
    """Small monotonic LIVE time-decay multiplier, capped at +18%."""
    minute=int(minute or 0)
    if engine==HT_HUNTER:
        progress=max(0.0,min(1.0,(minute-HT_OBSERVE_FROM)/max(1,HT_SIGNAL_TO-HT_OBSERVE_FROM)))
    elif engine==LATE_RISK:
        progress=max(0.0,min(1.0,(minute-LATE_OBSERVE_FROM)/max(1,LATE_SIGNAL_TO-LATE_OBSERVE_FROM)))
    else:
        progress=max(0.0,min(1.0,minute/90.0))
    return 1.0+0.18*progress

def trend_score(d:Mapping[str,float],minute:int=0,engine:str=CORE)->float:
    # xGOT gets its own weight: dangerous on-target quality should not be hidden
    # inside raw shot counts.  Missing xGOT remains neutral (zero).
    raw=(float(d.get("xg",0))*36+float(d.get("xgot",0))*22+float(d.get("shots",0))*4.5+
         float(d.get("shots_on_target",0))*11+float(d.get("big_chances",0))*18+
         float(d.get("corners",0))*2.5+float(d.get("shots_inside_box",0))*3+
         float(d.get("touches_box",0))*.85)
    return round(max(0.0,min(100.0,raw*time_weight(minute,engine))),1)

def cooldown_ready(current_minute:int,last_goal_minute:int|None)->bool:return last_goal_minute is None or int(current_minute)-int(last_goal_minute)>=POST_GOAL_COOLDOWN_MINUTES

def core_window(minute:int,is_halftime:bool=False)->bool:
    minute=int(minute or 0);return not is_halftime and minute>=FIRST_MATCH_WARMUP_MINUTE and not (46<=minute<SECOND_HALF_WARMUP_UNTIL) and minute<=CORE_MAX_NEW_MINUTE

def _adjust(base,timing_bonus):return round(max(0,min(100,float(base)+float(timing_bonus or 0))),1)

def ht_hunter(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
    minute=int(minute or 0);raw=trend_score(d,minute,HT_HUNTER);score=_adjust(raw,timing_bonus)
    if minute<HT_SIGNAL_FROM:return EngineDecision(HT_HUNTER,False,score,"collecting first-half trend")
    if minute>HT_SIGNAL_TO:return EngineDecision(HT_HUNTER,False,score,"first-half entry window closed at 38'")
    if not cooldown_ready(minute,last_goal_minute):return EngineDecision(HT_HUNTER,False,score,"5-minute post-goal cooldown")
    evidence=sum((d.get("xg",0)>=.25,d.get("xgot",0)>=.20,d.get("shots",0)>=3,d.get("shots_on_target",0)>=1,d.get("big_chances",0)>=1,d.get("touches_box",0)>=6))
    return EngineDecision(HT_HUNTER,score>=68 and evidence>=2,score,f"fresh evidence={evidence}; time_weight={time_weight(minute,HT_HUNTER):.3f}; timing={float(timing_bonus or 0):+.1f}")

def late_risk(minute:int,d:Mapping[str,float],last_goal_minute:int|None=None,timing_bonus:float=0)->EngineDecision:
    minute=int(minute or 0);raw=trend_score(d,minute,LATE_RISK);score=_adjust(raw,timing_bonus)
    if minute<LATE_SIGNAL_FROM:return EngineDecision(LATE_RISK,False,score,"collecting late trend")
    if minute>LATE_SIGNAL_TO:return EngineDecision(LATE_RISK,False,score,"late entry window closed at 85'")
    if not cooldown_ready(minute,last_goal_minute):return EngineDecision(LATE_RISK,False,score,"5-minute post-goal cooldown")
    evidence=sum((d.get("xg",0)>=.28,d.get("xgot",0)>=.22,d.get("shots",0)>=3,d.get("shots_on_target",0)>=1,d.get("big_chances",0)>=1,d.get("shots_inside_box",0)>=2,d.get("touches_box",0)>=7))
    return EngineDecision(LATE_RISK,score>=78 and evidence>=3,score,f"fresh evidence={evidence}; time_weight={time_weight(minute,LATE_RISK):.3f}; timing={float(timing_bonus or 0):+.1f}")
