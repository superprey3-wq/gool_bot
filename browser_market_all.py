"""Monkey LIVE TOTAL O/U collector restored from the old Bot-Hosting sources.

Flashscore is only the live match pool. Pricing is attempted in this order:
1) old LSApp LIVE lobtm -> ole2;
2) old BetB2B/1xBet live feed;
3) old Kambi/BetRivers live totals fallback.
Both OVER and UNDER are normalized into the same TOTAL market state.
"""
from __future__ import annotations
import os,time
import browser_market_node as node

node.MAX_EVENTS=max(20,min(100,int(os.getenv("GOOL_MARKET_MAX_EVENTS","100"))))
node.MAX_ODDS_EVENTS=100
node.MAX_RECORDS=max(500,min(4000,int(os.getenv("GOOL_MARKET_MAX_RECORDS","2400"))))
node.MAX_RECORDS_PER_EVENT=max(40,min(240,int(os.getenv("GOOL_MARKET_PER_EVENT","160"))))
node.ALLOWED_MARKETS={"OVER_UNDER"};node.MARKET_NAMES={"OVER_UNDER":"TOTAL"};node.MAX_ODD_BY_MARKET={"OVER_UNDER":12.0}

try: import betb2b_market_signal as betb2b
except Exception: betb2b=None
try:
 from gool_bot import kambi_live_odds as kambi
except Exception:
 try: import kambi_live_odds as kambi
 except Exception: kambi=None
try:
 from gool_bot import live_odds as old_live
except Exception:
 try: import live_odds as old_live
 except Exception: old_live=None


def _live_events(rows):
 out=[]
 for r in rows:
  if str(r.get("AB") or "")!="2":continue
  eid=r.get("AA")
  if not eid:continue
  out.append({"source":"flashscore","event_id":str(eid),"home":r.get("AE") or r.get("CX") or "","away":r.get("AF") or r.get("CX_2") or "","home_score":r.get("AG"),"away_score":r.get("AH"),"status":r.get("AC") or r.get("BC") or "LIVE","start_ts":r.get("AD"),"live_flag":"2","minute":r.get("BA"),"raw":{k:r[k] for k in list(r)[:32]}})
  if len(out)>=node.MAX_EVENTS:break
 return out


def _base(event,bid,book,scope,line,side,odd,source,ts):
 return {"event_id":event["event_id"],"home":event.get("home"),"away":event.get("away"),"score":f"{event.get('home_score') or ''}:{event.get('away_score') or ''}","status":event.get("status"),"bookmaker_id":bid,"bookmaker":book,"market":"TOTAL","market_raw":"OVER_UNDER","scope":scope,"line":line,"side":side,"odd":odd,"opening":None,"timestamp":ts,"source":source}


def _lsapp_rows(event,ts):
 if old_live is None:return []
 try: rows=old_live.fetch_live_odds(event["event_id"])
 except Exception as exc:
  node.LOG.info("OLD_LSAPP_FAIL event=%s %s",event["event_id"],type(exc).__name__);return []
 out=[]
 for row in rows or []:
  bid=row.get("bookmakerId");scope=str(row.get("bettingScope") or "FULL_TIME")
  for x in row.get("odds") or []:
   try: odd=float(x.get("value"));line=float((x.get("handicap") or {}).get("value"))
   except (TypeError,ValueError):continue
   side=str(x.get("selection") or "").upper()
   if side in {"OVER","UNDER"} and 1.01<odd<=12:out.append(_base(event,bid,f"lsapp_{bid}",scope,line,side,odd,"LIVE_OLE2",ts))
 return out


def _betb2b_rows(event,ts):
 if betb2b is None:return []
 try:
  k=betb2b._key(event.get("home"),event.get("away"))
  with betb2b._LOCK:
   mapped=(betb2b._EVENT_MAP.get(k) or {}).copy()
  eid=mapped.get("id")
  if not eid:return []
  detail=betb2b._request("/LiveFeed/GetGameZip",{"id":eid,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2})
  if not isinstance(detail,dict):return []
  overs=[];unders={}
  for group in detail.get("GE") or []:
   if int(group.get("G") or -1)!=4:continue
   for bucket in group.get("E") or []:
    for row in bucket or []:
     try:t=int(row.get("T"));line=float(row.get("P"));odd=float(row.get("C"))
     except (TypeError,ValueError):continue
     if odd<=1:continue
     if t==9:overs.append((int(row.get("CE") or 0),line,odd))
     elif t==10:unders[line]=odd
  if not overs:return []
  preferred=[x for x in overs if x[0]==1] or overs
  _,line,over=min(preferred,key=lambda x:abs(x[2]-2.0)+(abs(unders.get(x[1],5)-2.0) if x[1] in unders else 3))
  out=[_base(event,100000,"1xBet/BetB2B","FULL_TIME",line,"OVER",over,"BETB2B_1XBET",ts)]
  under=unders.get(line)
  if under and under>1:out.append(_base(event,100000,"1xBet/BetB2B","FULL_TIME",line,"UNDER",under,"BETB2B_1XBET",ts))
  return out
 except Exception:return []


def _kambi_rows(event,ts):
 if kambi is None:return []
 try:
  matched=kambi._find_event(event.get("home") or "",event.get("away") or "")
  if not matched:return []
  kid=matched.get("id");data=kambi._event_data(str(kid));out=[]
  for offer in data.get("betOffers") or []:
   type_name=str((offer.get("betOfferType") or {}).get("name") or "")
   criterion=str((offer.get("criterion") or {}).get("label") or "")
   key=f"{type_name} {criterion}".lower()
   if not any(x in key for x in ("over/under","total goals")):continue
   if "asian" in key or " by " in key or any(x in key for x in ("corner","card","shot","booking")):continue
   scope=kambi._scope_from_offer(criterion,type_name)
   for outcome in offer.get("outcomes") or []:
    if outcome.get("status")!="OPEN":continue
    label=str(outcome.get("label") or "").lower();otype=str(outcome.get("type") or "")
    side="OVER" if ("over" in label or otype=="OT_OVER") else "UNDER" if ("under" in label or otype=="OT_UNDER") else ""
    if not side:continue
    try: odd=float(outcome.get("odds"))/1000.0;raw=outcome.get("line");line=float(raw)/1000.0 if raw is not None else None
    except (TypeError,ValueError):continue
    if line is None or odd<=1.01 or not kambi._standard_line(line):continue
    out.append(_base(event,200000,"Kambi/BetRivers",scope,line,side,odd,"KAMBI",ts))
  if out:node.LOG.info("KAMBI_OU_MATCHED %s - %s rows=%d",event.get("home"),event.get("away"),len(out))
  return out
 except Exception as exc:
  node.LOG.info("KAMBI_TOTAL_FAIL event=%s %s",event["event_id"],type(exc).__name__);return []


def _fetch_event_odds(lib,events):
 b2=0
 if betb2b is not None:
  try:b2=betb2b.sample_live(force=True)
  except Exception as exc:node.LOG.info("BETB2B_CYCLE_FAIL %s",type(exc).__name__)
 records=[];probes=[];ts=node._now_iso()
 for event in events[:node.MAX_ODDS_EVENTS]:
  a=_lsapp_rows(event,ts);b=_betb2b_rows(event,ts);c=_kambi_rows(event,ts);merged=a+b+c
  records.extend(merged[:node.MAX_RECORDS_PER_EVENT])
  over=sum(1 for x in merged if x.get("side")=="OVER");under=sum(1 for x in merged if x.get("side")=="UNDER")
  probes.append({"event_id":event["event_id"],"home":event.get("home"),"away":event.get("away"),"status":200,"ok":bool(merged),"records":len(merged),"entries":len(a),"source":"OLD_MULTI","lsapp":len(a),"betb2b":len(b),"kambi":len(c),"over":over,"under":under})
  node.LOG.info("OLD_PROGRUZ event=%s lsapp=%d betb2b=%d kambi=%d over=%d under=%d records=%d",event["event_id"],len(a),len(b),len(c),over,under,len(merged))
  if len(records)>=node.MAX_RECORDS:break
 node.LOG.info("OLD_PROGRUZ_CYCLE live=%d betb2b_priced=%d records=%d",len(events),b2,len(records))
 return node._apply_history(records[:node.MAX_RECORDS]),probes,[]

node._flash_events=_live_events
node._fetch_event_odds=_fetch_event_odds

if __name__=="__main__":
 node.LOG.info("GOOL_MARKET_LIVE source=OLD_BOT_HOSTING_MULTI TOTAL_OVER+TOTAL_UNDER all_live=on")
 node.main()
