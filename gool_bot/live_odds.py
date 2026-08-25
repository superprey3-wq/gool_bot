"""Current in-play totals from Flashscore/LSApp LIVE endpoints only."""
from __future__ import annotations
import logging,os
from typing import Any
import requests
logger=logging.getLogger("live_odds")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
ROOTS=("https://2.ds.lsapp.eu/pq_graphql","https://global.ds.lsapp.eu/pq_graphql")
PROJECT_ID=os.getenv("LIVE_ODDS_PROJECT_ID","2");GEO=os.getenv("LIVE_ODDS_GEO","US");SUBDIVISION=os.getenv("LIVE_ODDS_SUBDIVISION","USAZ")
HEADERS={"User-Agent":UA,"Accept":"application/json, text/plain, */*","Referer":"https://www.flashscore.com/"}
def _query(params:dict[str,Any])->dict[str,Any]:
    for root in ROOTS:
        try:
            r=requests.get(root,params=params,headers=HEADERS,timeout=12)
            if r.status_code==200:
                p=r.json()
                if isinstance(p,dict):return p
        except (requests.RequestException,ValueError):continue
    return {}
def _live_menu(event_id):
    p=_query({"_hash":"lobtm","eventId":event_id,"projectId":PROJECT_ID,"geoIpCode":GEO,"geoIpSubdivisionCode":SUBDIVISION})
    return (p.get("data") or {}).get("getLiveOddsBettingTypeMenu") or {}
def _live_bookmaker_market(event_id,bookmaker_id,scope):
    p=_query({"_hash":"ole2","eventId":event_id,"bookmakerId":bookmaker_id,"betType":"OVER_UNDER","betScope":scope})
    return (p.get("data") or {}).get("findLiveOddsForBookmaker") or {}
def _normalise_over_under(event_id,bookmaker_id,scope,market):
    overview=market.get("eventOddsOverview") or {}
    if str(overview.get("type") or "")!="OVER_UNDER":return None
    odds=[]
    for op in overview.get("opportunities") or []:
        try:line=float((op.get("handicap") or {}).get("value"))
        except (TypeError,ValueError):continue
        for selection,key in (("OVER","over"),("UNDER","under")):
            item=op.get(key) or {}
            if item.get("active") is False or item.get("value") in (None,""):continue
            try:value=float(item.get("value"))
            except (TypeError,ValueError):continue
            if value<=1.0:continue
            odds.append({"selection":selection,"value":value,"active":True,"handicap":{"value":line},"source":"LIVE_OLE2"})
    if not odds:return None
    return {"eventId":event_id,"bookmakerId":bookmaker_id,"bettingType":"OVER_UNDER","bettingScope":scope,"hasLiveBettingOffers":True,"liveVerified":True,"source":"LIVE_OLE2","odds":odds}
def _primary_live_rows(event_id):
    menu=_live_menu(event_id)
    if not menu:return []
    rows=[];seen=set()
    for item in menu.get("items") or []:
        if item.get("isActive") is False or str(item.get("bettingType") or "")!="OVER_UNDER":continue
        scope=str(item.get("bettingScope") or "FULL_TIME")
        if scope not in {"FIRST_HALF","SECOND_HALF","FULL_TIME"}:continue
        for bookmaker_id in item.get("bookmakerIds") or []:
            try:bid=int(bookmaker_id)
            except (TypeError,ValueError):continue
            key=(bid,scope)
            if key in seen:continue
            seen.add(key);row=_normalise_over_under(event_id,bid,scope,_live_bookmaker_market(event_id,bid,scope))
            if row:rows.append(row)
    return rows
def fetch_live_odds(event_id):
    rows=_primary_live_rows(event_id)
    if rows:logger.info("LIVE odds %s: %d O/U rows via LIVE_OLE2",event_id,len(rows))
    else:logger.info("LIVE odds %s: no usable O/U rows",event_id)
    return rows
