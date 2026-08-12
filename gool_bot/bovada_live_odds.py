"""Live football total-goals odds from Bovada's public JSON feed."""
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
        logger.info("Bovada score changed %s %s -> %s; forcing fresh LIVE odds",key,previous,score)
        invalidate_live_cache()
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
        r=requests.get(LIVE_URL,timeout=12,headers={"User-Agent":"Mozilla/5.0","Accept":"application/json","Cache-Control":"no-cache"}); r.raise_for_status(); payload=r.json(); events=[]; _walk_events(payload,events)
        _CACHE_EVENTS=events; _CACHE_AT=now; logger.info("Bovada LIVE events loaded: %d",len(events))
    except (requests.RequestException,ValueError) as exc:logger.info("Bovada LIVE unavailable: %s",exc)
    return _CACHE_EVENTS
def _event_teams(event:dict[str,Any])->tuple[str,str]:
    desc=str(event.get("description") or "")
    for sep in (" vs "," v "," - "):
        if sep in desc:
            a,b=desc.split(sep,1); return a.strip(),b.strip()
    return desc,""
def _find_event(home:str,away:str)->dict[str,Any]|None:
    best=None; best_score=0.0
    for event in _live_events():
        eh,ea=_event_teams(event); direct=(_ratio(home,eh)+_ratio(away,ea))/2; reverse=(_ratio(home,ea)+_ratio(away,eh))/2; score=max(direct,reverse)
        if score>best_score:best_score,best=score,event
    if best is not None and best_score>=0.68:
        logger.info("Bovada match %.2f: %s — %s -> %s",best_score,home,away,best.get("description")); return best
    return None

def _over_prices(event:dict[str,Any],scope:str)->dict[float,list[float]]:
    prices:dict[float,list[float]]={}
    for group in event.get("displayGroups") or []:
        if not isinstance(group,dict):continue
        gl=str(group.get("description") or "").lower()
        if any(x in gl for x in ("corner","card","booking")):continue
        for market in group.get("markets") or []:
            if not isinstance(market,dict) or str(market.get("status") or "O")!="O":continue
            ml=str(market.get("description") or "").lower()
            if "total" not in ml or any(x in ml for x in ("corner","card","booking")):continue
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome,dict) or str(outcome.get("status") or "O")!="O":continue
                sel=str(outcome.get("description") or ""); sl=sel.lower()
                if not sl.startswith("over"):continue
                is_first=any(x in sl for x in ("l1h","1st half","first half"))
                is_second=any(x in sl for x in ("2nd half","second half","l2h"))
                if scope=="FULL_TIME" and (is_first or is_second):continue
                if scope=="FIRST_HALF" and not is_first:continue
                price=outcome.get("price") or {}
                try:line=float(price.get("handicap")); odd=float(price.get("decimal"))
                except (TypeError,ValueError):continue
                if odd>1.001:prices.setdefault(line,[]).append(odd)
    return prices

def get_all_full_time_over_odds(home:str,away:str)->list[dict[str,Any]]:
    event=_find_event(home,away)
    if not event:return []
    rows=[]
    for line,vals in sorted(_over_prices(event,"FULL_TIME").items()):
        if vals:rows.append({"scope":"FULL_TIME","line":float(line),"odd":float(min(vals)),"bookmakers":1,"source":"Bovada","event_id":event.get("id"),"event_name":event.get("description")})
    return rows

def get_goal_total_odds(home:str,away:str,home_score:int,away_score:int)->list[dict[str,Any]]:
    _refresh_if_score_changed(home,away,home_score,away_score)
    goals=int(home_score or 0)+int(away_score or 0); targets=(goals+.5,goals+1.5); all_rows={float(r["line"]):r for r in get_all_full_time_over_odds(home,away)}; rows=[]
    for idx,target in enumerate(targets,1):
        r=dict(all_rows.get(float(target)) or {})
        if r:r["goal_step"]=idx; rows.append(r)
    return rows

def get_first_half_total_odds(home:str,away:str,home_score:int,away_score:int)->list[dict[str,Any]]:
    """Return exact +1 and +2 goal total lines for the remainder of the first half."""
    _refresh_if_score_changed(home,away,home_score,away_score)
    event=_find_event(home,away)
    if not event:return []
    goals=int(home_score or 0)+int(away_score or 0); targets=(goals+.5,goals+1.5); available=_over_prices(event,"FIRST_HALF"); rows=[]
    for idx,target in enumerate(targets,1):
        vals=available.get(float(target),[])
        if vals:
            rows.append({"scope":"FIRST_HALF","line":float(target),"odd":float(min(vals)),"bookmakers":1,"source":"Bovada","goal_step":idx,"event_id":event.get("id"),"event_name":event.get("description")})
    return rows

def get_first_half_goal_odds(home:str,away:str,home_score:int,away_score:int)->dict[str,Any]|None:
    rows=get_first_half_total_odds(home,away,home_score,away_score)
    return rows[0] if rows else None
