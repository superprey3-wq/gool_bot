"""Market selector for GOOL V3 FULL_TIME / FIRST_HALF / SECOND_HALF totals."""
from __future__ import annotations
import math,os,sqlite3,time
from pathlib import Path
from live_odds import fetch_live_odds

SCOPE_MAP={"FULL_TIME":"FULL_TIME","FIRST_HALF":"FIRST_HALF","SECOND_HALF":"SECOND_HALF"}
LOCAL_DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"))

def _pois(k,lam):return math.exp(-lam)*(lam**k)/math.factorial(k)

def outcome_probs(current_goals:float,line:float,side:str,lam:float):
    win=push=0.0;maxk=max(12,int(math.ceil(lam+8*max(1.0,lam**.5))));total_mass=0.0
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
    return win,push,max(0.0,1.0-win-push)

def fair_odd(win:float,push:float)->float|None:
    return None if win<=0 else (1.0-push)/win

def _local_rows(event_id,period,max_age=150):
    if not LOCAL_DB.exists():return []
    scope=SCOPE_MAP.get(period,period);cut=time.time()-max_age
    try:
        c=sqlite3.connect(str(LOCAL_DB),timeout=3)
        rows=c.execute("SELECT ts,source,bookmaker,line,side,odd FROM odds WHERE event_id=? AND market='TOTAL' AND scope=? AND ts>=? AND line IS NOT NULL AND odd IS NOT NULL ORDER BY ts DESC",(str(event_id),scope,cut)).fetchall();c.close()
    except Exception:return []
    out=[];seen=set()
    for ts,source,book,line,side,odd in rows:
        try:line=float(line);odd=float(odd);side=str(side).upper()
        except Exception:continue
        if side not in {"OVER","UNDER"} or odd<=1.05 or odd>5.0:continue
        key=(str(book),side,line)
        if key in seen:continue
        seen.add(key);out.append({"period":period,"side":side,"line":line,"odd":odd,"source":f"Monkey/{source or book or 'market'}"})
    return out

def fetch_period_totals(event_id:str,period:str):
    local=_local_rows(event_id,period)
    if local:return local
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

def _effective_lambda(dec,history_mult):
    return max(.01,min(4.5,float(dec.lambda_remaining)*max(.88,min(1.12,float(history_mult or 1.0)))))

def _direction_allowed(dec,side):
    """Only the football model decides direction. The market layer must not add a second quality gate."""
    side=str(side).upper();direction=str(getattr(dec,"direction","NO_BET") or "NO_BET").upper()
    return direction in {"OVER","UNDER"} and side==direction and getattr(dec,"line",None) is not None

def _model_only(dec,history_mult=1.0,min_probability=.68):
    """Use V3's own canonical half-goal line; never manufacture an easy distant total."""
    side=str(getattr(dec,"direction","NO_BET") or "NO_BET").upper()
    if not _direction_allowed(dec,side):return None
    try:line=float(dec.line)
    except (TypeError,ValueError):return None
    lam=_effective_lambda(dec,history_mult);win,push,loss=outcome_probs(float(dec.current_goals),line,side,lam)
    # The V3 model has already cleared its football-quality gate. Keep only the
    # probability floor here so history adjustment cannot turn a strong model
    # decision into a contradictory low-probability pick.
    if win<min_probability:return None
    fair=fair_odd(win,push)
    return {"period":dec.period,"side":side,"line":line,"odd":None,"source":"MODEL_ONLY","model_probability":round(win*100,1),"push_probability":round(push*100,1),"fair_odd":round(fair,2) if fair else None,"value_edge":None,"ev":None,"effective_lambda":round(lam,3),"history_mult":round(history_mult,3),"price_verified":False}

def select_best(dec,rows,min_probability=0.58,min_value_pp=4.0,history_mult=1.0,allow_model_only=True,max_line_distance=1.0):
    """Price the V3 football decision. Odds are optional and cannot reverse/create a signal."""
    direction=str(getattr(dec,"direction","NO_BET") or "NO_BET").upper()
    if direction not in {"OVER","UNDER"} or getattr(dec,"line",None) is None:return None
    scored=[];effective_lam=_effective_lambda(dec,history_mult);anchor=float(dec.line)
    for r in rows or []:
        side=str(r["side"]).upper();line=float(r["line"]);odd=float(r["odd"])
        if not _direction_allowed(dec,side):continue
        if abs(line-anchor)>float(max_line_distance):continue
        win,push,loss=outcome_probs(dec.current_goals,line,side,effective_lam);fair=fair_odd(win,push)
        if not fair:continue
        implied=1.0/odd;value_pp=(win-implied)*100.0;ev=win*(odd-1.0)-loss
        if win<min_probability or value_pp<min_value_pp or ev<0.025:continue
        distance=abs(line-anchor);quality=win*100+value_pp*1.8+ev*12-distance*4.0
        scored.append((quality,{**r,"model_probability":round(win*100,1),"push_probability":round(push*100,1),"fair_odd":round(fair,2),"value_edge":round(value_pp,1),"ev":round(ev,3),"effective_lambda":round(effective_lam,3),"history_mult":round(history_mult,3),"price_verified":True}))
    if scored:
        scored.sort(key=lambda x:x[0],reverse=True);return scored[0][1]
    return _model_only(dec,history_mult) if allow_model_only else None
