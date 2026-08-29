"""Two-way fair probability helpers for PROGRUZ. Pure Python, no API."""
from __future__ import annotations

def implied(odd):
    try: odd=float(odd)
    except (TypeError,ValueError): return 0.0
    return 1.0/odd if odd>1.0 else 0.0

def fair_pair(over_odd,under_odd):
    over=implied(over_odd); under=implied(under_odd); total=over+under
    if total<=0:return {}
    return {"over":over/total,"under":under/total,"vig":max(0.0,total-1.0)}

def fair_move_pp(old_over,old_under,new_over,new_under,side):
    old=fair_pair(old_over,old_under); new=fair_pair(new_over,new_under)
    key="over" if str(side).upper()=="OVER" else "under"
    if not old or not new:return None
    return round((new[key]-old[key])*100.0,3)
