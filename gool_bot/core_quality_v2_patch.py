"""CORE Quality V2: conservative live-goal selection.

Research-informed guard on top of the legacy pressure engine:
- never treats cumulative match stats as recent momentum when no baseline exists;
- requires recent pressure to be confirmed by multiple independent indicators;
- adjusts for score effects (comfortable leaders need stronger fresh evidence);
- keeps the public 80/100 + 75% gates unchanged, but makes 80 harder to earn.

This patch targets CORE only. 1H/2H and Monkey engines are untouched.
"""
from __future__ import annotations
import logging

logger=logging.getLogger("core_quality_v2")

try:
    import visual_feed_unified_bot
    ub=visual_feed_unified_bot.unified_bot
except Exception:
    import unified_bot as ub

_original=ub.calculate_goal_pressure

def _pair_total(values,key):
    try:
        a,b=values.get(key,(0.0,0.0)); return float(a or 0)+float(b or 0)
    except Exception:return 0.0

def _delta(values,previous,key):
    if not previous:return 0.0
    return max(0.0,_pair_total(values,key)-_pair_total(previous,key))

def _confirmed_components(values,previous):
    if not previous:return [],{}
    d={
        "xg":_delta(values,previous,"xg"),
        "shots":_delta(values,previous,"shots"),
        "sot":_delta(values,previous,"shots_on_target"),
        "big":_delta(values,previous,"big_chances"),
        "inside":_delta(values,previous,"shots_inside_box"),
        "touches":_delta(values,previous,"touches_box"),
        "corners":_delta(values,previous,"corners"),
    }
    c=[]
    if d["xg"]>=0.15:c.append("xg")
    if d["sot"]>=1:c.append("sot")
    if d["shots"]>=3:c.append("shots")
    if d["big"]>=1:c.append("big")
    if d["inside"]>=2:c.append("inside")
    if d["touches"]>=6:c.append("touches")
    if d["corners"]>=2:c.append("corners")
    return c,d

def calculate_goal_pressure_quality_v2(match,values,previous=None):
    r=_original(match,values,previous)
    minute=int(getattr(match,"minute",0) or 0)
    goals=int(getattr(match,"home_score",0) or 0)+int(getattr(match,"away_score",0) or 0)
    lead=abs(int(getattr(match,"home_score",0) or 0)-int(getattr(match,"away_score",0) or 0))
    components,d=_confirmed_components(values,previous)

    # Critical reliability rule: without an 8-minute baseline cumulative stats are
    # not momentum. Observe the match first instead of firing from totals-to-date.
    if not previous:
        old=float(r.score); r.score=min(float(r.score),79.0); r.momentum=0.0
        r.reasons=["нужен предыдущий live-срез для подтверждения давления"]
        logger.info("CORE_QV2_REJECT event=%s minute=%s reason=no_baseline raw=%.1f final=%.1f",getattr(match,"event_id",""),minute,old,r.score)
        return r

    confirmations=len(components)
    raw=float(r.score)

    # A single noisy statistic is not sustained pressure. Two independent recent
    # signals are the minimum; late/comfortable-lead states require three.
    required=2
    if minute>=78 or (lead>=2 and minute>=55):required=3
    if confirmations<required:
        r.score=min(float(r.score),79.0)

    # Score effects: teams protecting a multi-goal lead commonly reduce attacking
    # output. Only fresh, broad pressure is allowed to overcome this context.
    if lead>=2 and minute>=55:
        if confirmations<4 or (d.get("sot",0)<1 and d.get("xg",0)<0.25):
            r.score=min(float(r.score),79.0)

    # Very late signals need genuine chance creation, not possession/old volume.
    if minute>=82 and d.get("sot",0)<1 and d.get("xg",0)<0.20 and d.get("big",0)<1:
        r.score=min(float(r.score),76.0)

    # Reward breadth only modestly; the existing model still supplies the score.
    if confirmations>=4 and float(r.score)>=78:
        r.score=min(100.0,float(r.score)+min(3.0,(confirmations-3)*1.0))

    if float(r.score)!=raw:
        logger.info("CORE_QV2_ADJUST event=%s minute=%s score=%s:%s raw=%.1f final=%.1f confirmations=%d/%d components=%s dxg=%.2f dsot=%.0f dshots=%.0f lead=%d goals=%d",getattr(match,"event_id",""),minute,getattr(match,"home_score",0),getattr(match,"away_score",0),raw,r.score,confirmations,required,",".join(components) or "none",d.get("xg",0),d.get("sot",0),d.get("shots",0),lead,goals)
    else:
        logger.info("CORE_QV2_OK event=%s minute=%s master=%.1f confirmations=%d/%d components=%s",getattr(match,"event_id",""),minute,r.score,confirmations,required,",".join(components) or "none")
    return r

ub.calculate_goal_pressure=calculate_goal_pressure_quality_v2
logger.info("CORE Quality V2 active | baseline required | multi-metric persistence | score-effects guard | late guard")
