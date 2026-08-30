"""Market selector for GOOL V3 FULL_TIME / FIRST_HALF / SECOND_HALF totals."""
from __future__ import annotations
import math
from live_odds import fetch_live_odds

SCOPE_MAP={"FULL_TIME":"FULL_TIME","FIRST_HALF":"FIRST_HALF","SECOND_HALF":"SECOND_HALF"}

def _pois(k,lam):
    return math.exp(-lam)*(lam**k)/math.factorial(k)

def outcome_probs(current_goals:float,line:float,side:str,lam:float):
    win=push=0.0
    maxk=max(12,int(math.ceil(lam+8*max(1.0,lam**.5))))
    total_mass=0.0
    for k in range(maxk+1):
        p=_pois(k,lam);total_mass+=p;final=current_goals+k
        if side=="OVER":
            if final>line:win+=p
            elif abs(final-line)<1e-9:push+=p
        else:
            if final<line:win+=p
            elif abs(final-line)<1e-9:push+=p
    tail=max(0.0,1.0-total_mass)
    if side=="OVER":win+=tail
    loss=max(0.0,1.0-win-push)
    return win,push,loss

def fair_odd(win:float,push:float)->float|None:
    if win<=0:return None
    return (1.0-push)/win

def fetch_period_totals(event_id:str,period:str):
    scope=SCOPE_MAP.get(period,period);rows=[]
    try:entries=fetch_live_odds(str(event_id))
    except Exception:return []
    for entry in entries or []:
        if str(entry.get("bettingScope") or "")!=scope:continue
        for item in entry.get("odds") or []:
            side=str(item.get("selection") or "").upper()
            if side not in {"OVER","UNDER"} or item.get("active") is False:continue
            try:line=float((item.get("handicap") or {}).get("value"));odd=float(item.get("value"))
            except (TypeError,ValueError,AttributeError):continue
            if odd<=1.05 or odd>5.0:continue
            rows.append({"period":period,"side":side,"line":line,"odd":odd,"source":"Flashscore/LSApp"})
    return rows

def select_best(dec,rows,min_probability=0.58,min_value_pp=4.0,history_mult=1.0):
    """Choose one exact market. Recent form is only a bounded prior, never a trigger."""
    scored=[];effective_lam=max(.01,min(4.5,float(dec.lambda_remaining)*max(.88,min(1.12,float(history_mult or 1.0)))))
    for r in rows or []:
        side=r["side"];line=float(r["line"]);odd=float(r["odd"])
        if side=="OVER" and not (dec.threat>=55 and dec.potential>=55 and dec.p_goal_10m>=14):continue
        if side=="UNDER" and not (dec.threat<=42 and dec.p_goal_10m<=18):continue
        win,push,loss=outcome_probs(dec.current_goals,line,side,effective_lam);fair=fair_odd(win,push)
        if not fair:continue
        implied=1.0/odd;value_pp=(win-implied)*100.0;ev=win*(odd-1.0)-loss
        if win<min_probability or value_pp<min_value_pp or ev<0.025:continue
        expected=dec.current_goals+effective_lam;distance=abs(line-expected)
        quality=win*100+value_pp*1.8+ev*12-distance*2.0
        scored.append((quality,{**r,"model_probability":round(win*100,1),"push_probability":round(push*100,1),"fair_odd":round(fair,2),"value_edge":round(value_pp,1),"ev":round(ev,3),"effective_lambda":round(effective_lam,3),"history_mult":round(history_mult,3)}))
    if not scored:return None
    scored.sort(key=lambda x:x[0],reverse=True)
    return scored[0][1]
