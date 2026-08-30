"""Market selector for GOOL V3 FULL_TIME / FIRST_HALF / SECOND_HALF totals."""
from __future__ import annotations
import math
from live_odds import fetch_live_odds

SCOPE_MAP={"FULL_TIME":"FULL_TIME","FIRST_HALF":"FIRST_HALF","SECOND_HALF":"SECOND_HALF"}

def _pois(k,lam):
    return math.exp(-lam)*(lam**k)/math.factorial(k)

def outcome_probs(current_goals:float,line:float,side:str,lam:float):
    """Return win/push/loss probabilities for a totals selection."""
    win=push=0.0
    maxk=max(12,int(math.ceil(lam+8*max(1.0,lam**.5))))
    for k in range(maxk+1):
        p=_pois(k,lam)
        final=current_goals+k
        if side=="OVER":
            if final>line:win+=p
            elif abs(final-line)<1e-9:push+=p
        else:
            if final<line:win+=p
            elif abs(final-line)<1e-9:push+=p
    tail=max(0.0,1.0-sum(_pois(k,lam) for k in range(maxk+1)))
    if side=="OVER":win+=tail
    else:pass
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
            try:
                line=float((item.get("handicap") or {}).get("value"));odd=float(item.get("value"))
            except (TypeError,ValueError,AttributeError):continue
            if odd<=1.05 or odd>5.0:continue
            rows.append({"period":period,"side":side,"line":line,"odd":odd,"source":"Flashscore/LSApp"})
    return rows

def select_best(dec,rows,min_probability=0.58,min_value_pp=4.0):
    """Choose one concrete total. Direction must agree with live football state."""
    scored=[]
    for r in rows or []:
        side=r["side"];line=float(r["line"]);odd=float(r["odd"])
        # Do not accept an OVER from a quiet state or an UNDER from a hot state.
        if side=="OVER" and not (dec.threat>=55 and dec.potential>=55 and dec.p_goal_10m>=14):continue
        if side=="UNDER" and not (dec.threat<=42 and dec.p_goal_10m<=18):continue
        win,push,loss=outcome_probs(dec.current_goals,line,side,dec.lambda_remaining)
        fair=fair_odd(win,push)
        if not fair:continue
        implied=1.0/odd
        value_pp=(win-implied)*100.0
        ev=win*(odd-1.0)-loss
        if win<min_probability or value_pp<min_value_pp or ev<0.025:continue
        # Avoid trivial lines too far from current score / model centre.
        expected=dec.current_goals+dec.lambda_remaining
        distance=abs(line-expected)
        quality=win*100+value_pp*1.8+ev*12-distance*2.0
        scored.append((quality,{**r,"model_probability":round(win*100,1),"push_probability":round(push*100,1),"fair_odd":round(fair,2),"value_edge":round(value_pp,1),"ev":round(ev,3)}))
    if not scored:return None
    scored.sort(key=lambda x:x[0],reverse=True)
    return scored[0][1]
