"""Flashscore/LSApp-first period and full-time market selection for GOOL CORE.

Only markets present in the current Flashscore/LSApp event odds may enter the
CORE recommendation set. External providers are attached later as confirmation
and never create or replace the primary line.
"""
from __future__ import annotations
import unified_bot
import live_candidate_patch as lcp


def _ls_scope(entries,m,p,scope):
    out=[]
    for r in unified_bot._recommendations(entries,m,p):
        if str(r.get("scope") or "")!=scope:continue
        try:odd=float(r.get("odd"))
        except (TypeError,ValueError):continue
        if odd<=1.001:continue
        out.append(dict(r,source="Flashscore/LSApp",primary_source=True))
    return out


def _whole_match_candidates(entries,m,p):
    goals=int(m.home_score)+int(m.away_score);out=[]
    for r in _ls_scope(entries,m,p,"FULL_TIME"):
        try:line=float(r["line"]);odd=float(r["odd"])
        except (KeyError,TypeError,ValueError):continue
        if line<=goals or odd<1.05 or odd>8.0:continue
        conf=unified_bot._model_confidence(p.score,p.momentum,line,goals,"FULL_TIME",m.minute,odd)
        edge=round(conf-(100/odd),1);needed=unified_bot._goals_needed_for_over(line,goals)
        utility=conf+edge*.8-abs(odd-1.90)*3-max(0,needed-1)*4
        out.append(dict(r,confidence=conf,value_edge=edge,needed_goals=needed,whole_match_utility=utility))
    if out:max(out,key=lambda r:(float(r.get("whole_match_utility",-999)),float(r.get("value_edge",-999))))["full_match_best"]=True
    return out


def _first_half_row(entries,m,p):
    if int(m.minute or 0)>45 or m.is_halftime:return None
    goals=int(m.home_score)+int(m.away_score);target=goals+.5
    for r in _ls_scope(entries,m,p,"FIRST_HALF"):
        try:
            if abs(float(r.get("line"))-target)>1e-9:continue
            odd=float(r["odd"])
        except (TypeError,ValueError,KeyError):continue
        return dict(r,line=target,period_goal=True,confidence=unified_bot._model_confidence(p.score,p.momentum,target,goals,"FIRST_HALF",m.minute,odd))
    return None


def _target_goal_markets(entries,m,p):
    goals=int(m.home_score)+int(m.away_score);targets=(goals+.5,goals+1.5);rows=[]
    ls={float(r["line"]):r for r in _ls_scope(entries,m,p,"FULL_TIME") if r.get("line") is not None}
    for step,line in enumerate(targets,1):
        r=dict(ls.get(float(line)) or {})
        if not r:continue
        odd=float(r["odd"]);conf=unified_bot._model_confidence(p.score,p.momentum,line,goals,"FULL_TIME",m.minute,odd)
        r.update({"goal_step":step,"target_label":"ещё 1 гол" if step==1 else "ещё 2 гола","confidence":conf,"value_edge":round(conf-(100/odd),1)})
        rows.append(r)
    best=next((r for r in _whole_match_candidates(entries,m,p) if r.get("full_match_best")),None)
    if best:rows.append(best)
    first=_first_half_row(entries,m,p)
    if first:rows.append(first)
    return rows


def _market(entries,m,p):
    recs=_target_goal_markets(entries,m,p)
    r=next((x for x in recs if x.get("scope")=="FULL_TIME" and x.get("goal_step")==1),None) or next((x for x in recs if x.get("scope")=="FULL_TIME"),None)
    if not r:return recs,{"available":False,"primary_source":"Flashscore/LSApp"}
    odd=float(r["odd"])
    return recs,{"available":True,"scope":"FULL_TIME","line":float(r["line"]),"odd":odd,"bookmakers":r.get("bookmakers",1),"source":"Flashscore/LSApp","goal_step":r.get("goal_step"),"market_probability":round(100/odd,1),"primary_source":"Flashscore/LSApp"}

lcp._target_goal_markets=_target_goal_markets
lcp._market=_market
