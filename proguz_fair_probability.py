"""Two-way fair probability helpers for PROGRUZ.

Pure Python, no external API. Uses multiplicative and power de-vig methods and
returns a consensus plus method spread so Monkey can detect unstable pricing.
"""
from __future__ import annotations
import math


def implied(odd):
    try: odd=float(odd)
    except (TypeError,ValueError): return 0.0
    return 1.0/odd if odd>1.0 else 0.0


def _raw(over_odd,under_odd):
    over=implied(over_odd);under=implied(under_odd)
    return over,under,over+under


def fair_pair(over_odd,under_odd):
    """Multiplicative de-vig for a two-way market."""
    over,under,total=_raw(over_odd,under_odd)
    if total<=0:return {}
    return {"over":over/total,"under":under/total,"vig":total-1.0,"method":"multiplicative"}


def fair_pair_power(over_odd,under_odd):
    """Power de-vig: find k where q_over**k + q_under**k == 1."""
    over,under,total=_raw(over_odd,under_odd)
    if over<=0 or under<=0:return {}
    if abs(total-1.0)<1e-12:return {"over":over,"under":under,"vig":0.0,"method":"power","k":1.0}
    lo,hi=0.05,10.0
    def f(k):return over**k+under**k-1.0
    # f(k) is decreasing for probabilities in (0,1). Expand only if needed.
    while f(lo)<0 and lo>1e-6:lo*=0.5
    while f(hi)>0 and hi<100:hi*=2.0
    for _ in range(80):
        mid=(lo+hi)/2.0
        if f(mid)>0:lo=mid
        else:hi=mid
    k=(lo+hi)/2.0;po=over**k;pu=under**k;s=po+pu
    if s<=0:return {}
    return {"over":po/s,"under":pu/s,"vig":total-1.0,"method":"power","k":k}


def fair_consensus(over_odd,under_odd):
    """Average robust two-way fair probability across independent de-vig methods."""
    a=fair_pair(over_odd,under_odd);b=fair_pair_power(over_odd,under_odd)
    methods=[x for x in (a,b) if x]
    if not methods:return {}
    over=sum(x["over"] for x in methods)/len(methods);under=sum(x["under"] for x in methods)/len(methods)
    spread=(max(x["over"] for x in methods)-min(x["over"] for x in methods))*100.0 if len(methods)>1 else 0.0
    vig=sum(float(x.get("vig",0)) for x in methods)/len(methods)
    return {"over":over,"under":under,"vig":vig,"method_spread_pp":spread,"methods":[x["method"] for x in methods]}


def fair_move_pp(old_over,old_under,new_over,new_under,side):
    old=fair_consensus(old_over,old_under);new=fair_consensus(new_over,new_under)
    key="over" if str(side).upper()=="OVER" else "under"
    if not old or not new:return None
    return round((new[key]-old[key])*100.0,3)


def self_test():
    # Symmetric prices should be 50/50 after de-vig.
    a=fair_consensus(1.90,1.90)
    assert abs(a["over"]-.5)<1e-9 and abs(a["under"]-.5)<1e-9
    # Shortening OVER while UNDER drifts must increase fair OVER probability.
    d=fair_move_pp(1.95,1.85,1.72,2.08,"OVER")
    assert d is not None and d>0
    # Both methods must return normalized probabilities.
    for fn in (fair_pair,fair_pair_power):
        x=fn(1.80,2.05);assert x and abs(x["over"]+x["under"]-1.0)<1e-9
    return True


if __name__=="__main__":
    print("proguz_fair_probability self_test=ok" if self_test() else "self_test=failed")
