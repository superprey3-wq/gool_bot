"""Live football total-goals and BTTS odds from Bovada's public JSON feed."""
from __future__ import annotations
from difflib import SequenceMatcher
import logging, re, time
from typing import Any
import requests

logger=logging.getLogger("bovada_live_odds")
LIVE_URL="https://www.bovada.lv/services/sports/event/v2/events/A/description/soccer?lang=en&liveOnly=true"
_CACHE_TTL=25; _CACHE_AT=0.0; _CACHE_EVENTS:list[dict[str,Any]]=[]
_LAST_SCORE_BY_MATCH:dict[str,str]={}

def _norm(value:str)->str:
    value=str(value or "").lower().replace("utd","united").replace("fc ","").replace(" vsc","")
    value=re.sub(r"\([^)]*\)"," ",value); value=re.sub(r"[^a-z0-9а-яё]+"," ",value)
    return " ".join(value.split())
def _ratio(a:str,b:str)->float:
    a,b=_norm(a),_norm(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    if a in b or b in a:return 0.94
    return SequenceMatcher(None,a,b).ratio()
def _match_key(home:str,away:str)->str:return f"{_norm(home)}|{_norm(away)}"
def invalidate_live_cache()->None:
    global _CACHE_AT,_CACHE_EVENTS
    _CACHE_AT=0.0; _CACHE_EVENTS=[]
def _refresh_if_score_changed(home:str,away:str,home_score:int,away_score:int)->None:
    key=_match_key(home,away); score=f"{int(home_score or 0)}:{int(away_score or 0)}"; previous=_LAST_SCORE_BY_MATCH.get(key)
    if previous is not None and previous!=score:
        logger.info("Bovada score changed %s %s -> %s; forcing fresh LIVE odds",key,previous,score);invalidate_live_cache()
    _LAST_SCORE_BY_MATCH[key]=score
def _walk_events(node:Any,out:list[dict[str,Any]])->None:
    if isinstance(node,dict):
        if isinstance(node.get("displayGroups"),list) and node.get("description"):out.append(node)
        for v in node.values():_walk_events(v,out)
    elif isinstance(node,list):
        for v in node:_walk_events(v,out)
def _live_events()->list[dict[str,Any]]:
    global _CACHE_AT,_CACHE_EVENTS
    now=time.time()
    if _CACHE_EVENTS and now-_CACHE_AT<_CACHE_TTL:return _CACHE_EVENTS
    try:
        r=requests.get(LIVE_URL,timeout=12,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json","Cache-Control":"no-cache"});r.raise_for_status();events=[];_walk_events(r.json(),events);_CACHE_EVENTS=events;_CACHE_AT=now;logger.info("Bovada LIVE events loaded: %d",len(events))
    except (requests.RequestException,ValueError) as exc:logger.info("Bovada LIVE unavailable: %s",exc)
    return _CACHE_EVENTS
def _event_teams(event):
    desc=str(event.get("description") or "")
    for sep in (" vs "," v "," - "):
        if sep in desc:a,b=desc.split(sep,1);return a.strip(),b.strip()
    return desc,""
def _find_event(home,away):
    best=None;best_score=0.0
    for event in _live_events():
        eh,ea=_event_teams(event);direct=(_ratio(home,eh)+_ratio(away,ea))/2;reverse=(_ratio(home,ea)+_ratio(away,eh))/2;score=max(direct,reverse)
        if score>best_score:best_score,best=score,event
    if best is not None and best_score>=0.68:logger.info("Bovada match %.2f: %s — %s -> %s",best_score,home,away,best.get("description"));return best
    return None

def _over_prices(event:dict[str,Any],scope:str)->dict[float,list[float]]:
    prices={};scope=str(scope or "FULL_TIME").upper()
    for group in event.get("displayGroups") or []:
        if not isinstance(group,dict):continue
        gl=str(group.get("description") or "").lower()
        if any(x in gl for x in ("corner","card","booking")):continue
        for market in group.get("markets") or []:
            if not isinstance(market,dict) or str(market.get("status") or "O")!="O":continue
            ml=str(market.get("description") or "").lower()
            if "total" not in ml or any(x in ml for x in ("corner","card","booking","asian")):continue
            # Reject team totals here; auxiliary period strategies need match-period totals only.
            if "total goals o/u -" in ml or "team total" in ml:continue
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome,dict) or str(outcome.get("status") or "O")!="O":continue
                sl=str(outcome.get("description") or "").lower()
                if not sl.startswith("over"):continue
                text=f"{gl} {ml} {sl}"
                is_first=any(x in text for x in ("l1h","1st half","first half"))
                is_second=any(x in text for x in ("l2h","2nd half","second half"))
                if scope=="FULL_TIME" and (is_first or is_second):continue
                if scope=="FIRST_HALF" and not is_first:continue
                if scope=="SECOND_HALF" and not is_second:continue
                price=outcome.get("price") or {}
                try:line=float(price.get("handicap"));odd=float(price.get("decimal"))
                except (TypeError,ValueError):continue
                if odd>1.001 and abs(line*2-round(line*2))<1e-9:prices.setdefault(line,[]).append(odd)
    return prices

def get_all_full_time_over_odds(home,away):
    event=_find_event(home,away)
    if not event:return []
    return [{"scope":"FULL_TIME","line":float(line),"odd":float(min(vals)),"bookmakers":1,"source":"Bovada","event_id":event.get("id"),"event_name":event.get("description")} for line,vals in sorted(_over_prices(event,"FULL_TIME").items()) if vals]
def get_goal_total_odds(home,away,home_score,away_score):
    _refresh_if_score_changed(home,away,home_score,away_score);goals=int(home_score or 0)+int(away_score or 0);all_rows={float(r["line"]):r for r in get_all_full_time_over_odds(home,away)};rows=[]
    for idx,target in enumerate((goals+.5,goals+1.5),1):
        r=dict(all_rows.get(float(target)) or {})
        if r:r["goal_step"]=idx;rows.append(r)
    return rows
def get_first_half_total_odds(home,away,home_score,away_score):
    _refresh_if_score_changed(home,away,home_score,away_score);event=_find_event(home,away)
    if not event:return []
    goals=int(home_score or 0)+int(away_score or 0);available=_over_prices(event,"FIRST_HALF");rows=[]
    for idx,target in enumerate((goals+.5,goals+1.5),1):
        vals=available.get(float(target),[])
        if vals:rows.append({"scope":"FIRST_HALF","line":float(target),"odd":float(min(vals)),"bookmakers":1,"source":"Bovada","goal_step":idx,"event_id":event.get("id"),"event_name":event.get("description")})
    return rows
def get_second_half_over15(home,away):
    event=_find_event(home,away)
    if not event:return None
    vals=_over_prices(event,"SECOND_HALF").get(1.5,[])
    if not vals:return None
    return {"scope":"SECOND_HALF","line":1.5,"odd":float(min(vals)),"bookmakers":1,"source":"Bovada","event_id":event.get("id"),"event_name":event.get("description")}
def get_first_half_goal_odds(home,away,home_score,away_score):
    rows=get_first_half_total_odds(home,away,home_score,away_score);return rows[0] if rows else None
def get_first_half_over05(home,away):
    event=_find_event(home,away)
    if not event:return None
    vals=_over_prices(event,"FIRST_HALF").get(.5,[])
    if not vals:return None
    return {"market_type":"FIRST_HALF_GOAL","scope":"FIRST_HALF","line":.5,"odd":float(min(vals)),"selection":"OVER","source":"Bovada","event_id":event.get("id"),"event_name":event.get("description")}
def get_btts_yes(home,away):
    event=_find_event(home,away)
    if not event:return None
    best=None
    for group in event.get("displayGroups") or []:
        for market in group.get("markets") or []:
            if not isinstance(market,dict) or str(market.get("status") or "O")!="O":continue
            if str(market.get("description") or "").strip().lower()!="both teams to score":continue
            for outcome in market.get("outcomes") or []:
                if str(outcome.get("status") or "O")!="O" or str(outcome.get("description") or "").strip().lower()!="yes":continue
                try:odd=float((outcome.get("price") or {}).get("decimal"))
                except (TypeError,ValueError):continue
                if odd>1.001:best=min(best,odd) if best else odd
    return None if best is None else {"market_type":"BTTS","scope":"FULL_TIME","selection":"YES","odd":float(best),"source":"Bovada","event_id":event.get("id"),"event_name":event.get("description")}
