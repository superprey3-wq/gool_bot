"""Force recommendation selection to use current LIVE stats + current LIVE odds only."""
from __future__ import annotations
import unified_bot


def _recommendations(entries,match,pressure):
    if match.minute<=45 and not match.is_halftime:
        scopes=("FIRST_HALF","FULL_TIME")
    elif match.is_halftime:
        scopes=("SECOND_HALF","FULL_TIME")
    else:
        scopes=("FULL_TIME",)
    rows=[]
    for scope in scopes:
        rows.extend(unified_bot._collect_scope_recommendations(entries,match,pressure,scope))
    for row in rows:
        try:
            odd=float(row.get("odd"));conf=float(row.get("confidence"))
            row["value_edge"]=round(conf-(100.0/odd),1)
        except (TypeError,ValueError,AttributeError):
            row["value_edge"]=None
        row.pop("best_bet",None)
    eligible=[r for r in rows if r.get("scope")=="FULL_TIME" and r.get("value_edge") is not None]
    if eligible:max(eligible,key=lambda r:(float(r.get("value_edge",-999)),float(r.get("confidence",0))))["best_bet"]=True
    return rows

unified_bot._recommendations=_recommendations
