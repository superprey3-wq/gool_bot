"""MonkeyBytes LIVE TOTAL O/U collector using the old Bot-Hosting LSApp flow.

The old working branch did not use the generic `_hash=oce` payload for in-play
pricing.  It first loaded the live betting-type menu (`lobtm`) and then queried
an active bookmaker/market with `ole2`.  Restore that exact path here while
keeping the lightweight v6 state/history machinery around it.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests
import browser_market_node as node

node.MAX_EVENTS=max(20,min(100,int(os.getenv("GOOL_MARKET_MAX_EVENTS","60"))))
node.MAX_ODDS_EVENTS=max(4,min(24,int(os.getenv("GOOL_MARKET_ODDS_EVENTS","24"))))
node.MAX_RECORDS=max(200,min(2200,int(os.getenv("GOOL_MARKET_MAX_RECORDS","1200"))))
node.MAX_RECORDS_PER_EVENT=max(40,min(220,int(os.getenv("GOOL_MARKET_PER_EVENT","140"))))
node.ALLOWED_MARKETS={"OVER_UNDER"}
node.MARKET_NAMES={"OVER_UNDER":"TOTAL"}
node.MAX_ODD_BY_MARKET={"OVER_UNDER":12.0}

# Exact settings from live-only-quant-foundation/gool_bot/live_odds.py.
ROOTS=("https://2.ds.lsapp.eu/pq_graphql","https://global.ds.lsapp.eu/pq_graphql")
PROJECT_ID=os.getenv("LIVE_ODDS_PROJECT_ID","2")
GEO=os.getenv("LIVE_ODDS_GEO","US")
SUBDIVISION=os.getenv("LIVE_ODDS_SUBDIVISION","USAZ")
HEADERS={
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36",
    "Accept":"application/json, text/plain, */*",
    "Referer":"https://www.flashscore.com/",
}


def _live_events(rows):
    events=[]
    for r in rows:
        if str(r.get("AB") or "") != "2":
            continue
        eid=r.get("AA")
        if not eid:
            continue
        events.append({
            "source":"flashscore", "event_id":str(eid),
            "home":r.get("AE") or r.get("CX") or "",
            "away":r.get("AF") or r.get("CX_2") or "",
            "home_score":r.get("AG"), "away_score":r.get("AH"),
            "status":r.get("AC") or r.get("BC") or "LIVE",
            "start_ts":r.get("AD"), "live_flag":"2", "minute":r.get("BA"),
            "raw":{k:r[k] for k in list(r)[:32]},
        })
        if len(events)>=node.MAX_EVENTS:
            break
    return events


def _query(params:dict[str,Any]):
    last_status=None
    for root in ROOTS:
        try:
            r=requests.get(root,params=params,headers=HEADERS,timeout=12)
            last_status=r.status_code
            if r.status_code==200:
                payload=r.json()
                if isinstance(payload,dict):
                    return payload, root, r.status_code
        except (requests.RequestException,ValueError):
            continue
    return {}, None, last_status


def _live_menu(event_id):
    payload,root,status=_query({
        "_hash":"lobtm", "eventId":event_id, "projectId":PROJECT_ID,
        "geoIpCode":GEO, "geoIpSubdivisionCode":SUBDIVISION,
    })
    return (payload.get("data") or {}).get("getLiveOddsBettingTypeMenu") or {},root,status


def _live_bookmaker_market(event_id,bookmaker_id,scope):
    payload,root,status=_query({
        "_hash":"ole2", "eventId":event_id, "bookmakerId":bookmaker_id,
        "betType":"OVER_UNDER", "betScope":scope,
    })
    return (payload.get("data") or {}).get("findLiveOddsForBookmaker") or {},root,status


def _normalise(event,bid,scope,market,ts):
    overview=market.get("eventOddsOverview") or {}
    if str(overview.get("type") or "") != "OVER_UNDER":
        return []
    out=[]
    for op in overview.get("opportunities") or []:
        try: line=float((op.get("handicap") or {}).get("value"))
        except (TypeError,ValueError): continue
        for side,key in (("OVER","over"),("UNDER","under")):
            item=op.get(key) or {}
            if item.get("active") is False or item.get("value") in (None,""):
                continue
            try: odd=float(item.get("value"))
            except (TypeError,ValueError): continue
            if odd<=1.01 or odd>12.0:
                continue
            out.append({
                "event_id":event.get("event_id"), "home":event.get("home"), "away":event.get("away"),
                "score":f"{event.get('home_score') or ''}:{event.get('away_score') or ''}",
                "status":event.get("status"), "bookmaker_id":int(bid), "bookmaker":f"book_{bid}",
                "market":"TOTAL", "market_raw":"OVER_UNDER", "scope":scope,
                "line":line, "side":side, "odd":odd, "opening":None,
                "timestamp":ts, "source":"LIVE_OLE2",
            })
    return out


def _fetch_event_odds_live_ole2(lib,events):
    records=[];probes=[]
    chosen=events[:node.MAX_ODDS_EVENTS]
    ts=node._now_iso()
    for event in chosen:
        eid=event["event_id"]
        menu,menu_root,menu_status=_live_menu(eid)
        items=menu.get("items") or []
        seen=set();before=len(records);market_calls=0
        for item in items:
            if item.get("isActive") is False or str(item.get("bettingType") or "")!="OVER_UNDER":
                continue
            scope=str(item.get("bettingScope") or "FULL_TIME")
            if scope not in {"FIRST_HALF","SECOND_HALF","FULL_TIME"}:
                continue
            for bookmaker_id in item.get("bookmakerIds") or []:
                try: bid=int(bookmaker_id)
                except (TypeError,ValueError): continue
                key=(bid,scope)
                if key in seen: continue
                seen.add(key);market_calls+=1
                market,_,_=_live_bookmaker_market(eid,bid,scope)
                records.extend(_normalise(event,bid,scope,market,ts))
                if len(records)>=node.MAX_RECORDS or len(records)-before>=node.MAX_RECORDS_PER_EVENT:
                    break
            if len(records)>=node.MAX_RECORDS or len(records)-before>=node.MAX_RECORDS_PER_EVENT:
                break
        parsed=len(records)-before
        probes.append({
            "event_id":eid,"home":event.get("home"),"away":event.get("away"),
            "status":menu_status,"ok":bool(menu),"records":parsed,
            "entries":len(items),"market_calls":market_calls,"source":"LIVE_OLE2",
            "root":menu_root,
        })
        node.LOG.info("LIVE_OLE2 event=%s menu=%d calls=%d records=%d",eid,len(items),market_calls,parsed)
        if len(records)>=node.MAX_RECORDS: break
        time.sleep(0.08)
    return node._apply_history(records[:node.MAX_RECORDS]),probes,[]

node._flash_events=_live_events
node._fetch_event_odds=_fetch_event_odds_live_ole2

if __name__=="__main__":
    node.LOG.info(
        "GOOL_MARKET_LIVE source=LIVE_OLE2 old_bot_hosting mode=LIVE_TOTAL_OU live_only=AB2 odds_events=%d records=%d",
        node.MAX_ODDS_EVENTS,node.MAX_RECORDS,
    )
    node.main()
