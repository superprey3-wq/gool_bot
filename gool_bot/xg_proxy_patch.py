"""Fallback xG proxy when Flashscore does not expose xG.

This is deliberately marked as estimated xG, not provider xG. Coefficients are
heuristic starting values and must later be calibrated against matches where
Flashscore xG is available.
"""
from __future__ import annotations
import logging
import live_engine,unified_bot
logger=logging.getLogger("xg_proxy")
_original=live_engine.parse_stats


def _pair(stats,key):
    try:a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
    except Exception:return 0.0,0.0


def _estimate_side(stats,i:int)->float:
    sot=_pair(stats,"shots_on_target")[i]; off=_pair(stats,"shots_off_target")[i]
    blocked=_pair(stats,"blocked_shots")[i]; inside=_pair(stats,"shots_inside_box")[i]
    outside=_pair(stats,"shots_outside_box")[i]; big=_pair(stats,"big_chances")[i]
    touches=_pair(stats,"touches_box")[i]; corners=_pair(stats,"corners")[i]
    # Shot quality hierarchy: big chances and shots on target carry most weight;
    # box activity adds context but is capped indirectly by small coefficients.
    est=(0.18*sot+0.055*off+0.035*blocked+0.075*inside+0.018*outside+
         0.30*big+0.012*touches+0.018*corners)
    return round(max(0.0,min(5.0,est)),3)


def parse_stats(body):
    out=_original(body)
    if "xg" not in out or sum(out.get("xg",(0,0)))<=0:
        proxy=(_estimate_side(out,0),_estimate_side(out,1))
        if sum(proxy)>0:
            out["xg"]=proxy;out["xg_is_proxy"]=(1.0,1.0)
            logger.info("XG_PROXY home=%.3f away=%.3f",proxy[0],proxy[1])
    return out

live_engine.parse_stats=parse_stats
unified_bot.parse_stats=parse_stats
