"""Make BEST BET receive real live total candidates even when exact +0.5/+1.5 lines are absent.

The normal CORE market builder used to require exact goal-relative lines. Real LSApp
books frequently expose neighbouring lines (e.g. 2.0/2.25/2.75), which left BEST BET
with zero recommendations. Keep the same market pipeline and multi-source enrichment,
but choose the nearest sane full-time OVER line for each desired goal step.
"""
from __future__ import annotations
import logging
import live_candidate_patch as lc
import unified_bot

log=logging.getLogger("best_bet_input_reliability")


def _nearest_target_goal_markets(entries,m,p):
    goals=int(getattr(m,"home_score",0) or 0)+int(getattr(m,"away_score",0) or 0)
    desired=(goals+.5,goals+1.5)
    rows=[]
    for r in unified_bot._recommendations(entries,m,p):
        if str(r.get("scope") or "")!="FULL_TIME" or not lc._sane_price(r):
            continue
        try:
            line=float(r.get("line")); odd=float(r.get("odd"))
        except (TypeError,ValueError):
            continue
        if line<=goals:
            continue
        x=dict(r)
        x.setdefault("market_type","TOTAL_OVER")
        x.setdefault("market","TOTAL_OVER")
        x.setdefault("selection","OVER")
        x.setdefault("source","LSApp")
        rows.append(x)
    if not rows:
        return []

    # One candidate near "one more goal" and one near "two more goals".
    chosen=[];used=set()
    for step,target in enumerate(desired,1):
        options=[r for r in rows if float(r["line"]) not in used]
        if not options:
            break
        best=min(options,key=lambda r:(abs(float(r["line"])-target),abs(float(r["odd"])-1.80),-int(r.get("bookmakers") or 0)))
        # Do not jump to a wildly unrelated line. Quarter/half/whole lines nearby are fine.
        if abs(float(best["line"])-target)>1.0:
            continue
        used.add(float(best["line"]))
        best["goal_step"]=step
        best["target_label"]="ещё 1 гол" if step==1 else "ещё 2 гола"
        conf=unified_bot._model_confidence(p.score,p.momentum,float(best["line"]),goals,"FULL_TIME",m.minute,float(best["odd"]))
        best["confidence"]=conf
        best["selector_confidence"]=conf
        best["value_edge"]=round(conf-(100/float(best["odd"])),1)
        chosen.append(best)

    if not chosen:
        # Last-resort: best sane full-time line, still through all later safety gates.
        best=min(rows,key=lambda r:(abs(float(r["odd"])-1.80),-int(r.get("bookmakers") or 0)))
        best["goal_step"]=1
        best["target_label"]="ближайший LIVE-тотал"
        conf=unified_bot._model_confidence(p.score,p.momentum,float(best["line"]),goals,"FULL_TIME",m.minute,float(best["odd"]))
        best["confidence"]=conf;best["selector_confidence"]=conf;best["value_edge"]=round(conf-(100/float(best["odd"])),1)
        chosen=[best]

    eligible=[r for r in chosen if lc._sane_price(r)]
    if eligible:
        best=max(eligible,key=lambda r:(float(r.get("value_edge",-999)),int(r.get("confidence",0)),-abs(float(r.get("odd",9))-1.8)))
        best["best_bet"]=True
    return chosen

lc._target_goal_markets=_nearest_target_goal_markets
log.info("BEST BET input reliability active | nearest sane FT total lines enabled")
