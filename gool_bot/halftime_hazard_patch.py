"""Fix LIVE goal horizon at half-time.

The base engine treated minute 45 as two minutes remaining (47-45), which made
strong HT signals display ~10% next-goal probability. At HT the relevant horizon
is the full second half.
"""
from __future__ import annotations
import math
import live_candidate_patch as lc


def _hazards(match, master):
    rate=(2.7/90)*(.45+1.35*master/100)
    vals=[(1-math.exp(-rate*x))*100 for x in (5,10,15)]
    if getattr(match,'is_halftime',False):
        remain=49
    elif match.minute < 45:
        remain=max(0,47-match.minute)
    else:
        remain=max(0,94-match.minute)
    vals.append((1-math.exp(-rate*remain))*100)
    return tuple(round(min(92,x),1) for x in vals)

lc._hazards=_hazards
