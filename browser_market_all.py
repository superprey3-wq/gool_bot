"""Monkey LIVE market collector.

PROGRUZ continues to use TOTAL O/U only. BEST BET additionally receives conservative
live 1X2 and BTTS rows from Kambi/BetRivers when those offers are explicitly open.
"""
from __future__ import annotations
import os,re,time
import browser_market_node as node
node.MAX_EVENTS=max(20,min(100,int(os.getenv("GOOL_MARKET_MAX_EVENTS","100"))));node.MAX_ODDS_EVENTS=100;node.MAX_RECORDS=max(500,min(4000,int(os.getenv("GOOL_MARKET_MAX_RECORDS","2400"))));node.MAX_RECORDS_PER_EVENT=max(40,min(240,int(os.getenv("GOOL_MARKET_PER_EVENT","160"))));node.ALLOWED_MARKETS={"OVER_UNDER","HOME_DRAW_AWAY","BOTH_TEAMS_TO_SCORE"};node.MARKET_NAMES={"OVER_UNDER":"TOTAL","HOME_DRAW_AWAY":"1X2","BOTH_TEAMS_TO_SCORE":"BTTS"};node.MAX_ODD_BY_MARKET={"OVER_UNDER":12.0,"HOME_DRAW_AWAY":20.0,"BOTH_TEAMS_TO_SCORE":8.0}
try:import betb2b_market_signal as betb2b
except Exception:betb2b=None
try:from gool_bot import kambi_live_odds as kambi
except Exception:
 try:import kambi_live_odds as kambi
 except Exception:kambi=None
try:from gool_bot import live_odds as old_live
except Exception:
 try:import live_odds as old_live
 except Exception:old_live=None

def _num(v):
 m=re.search(r"(\d{1,3})",str(v or ""));return int(m.group(1)) if m else None
def _status_text(r):return str(r.get("AC") or r.get("BC") or "LIVE").upper()
def _kickoff_elapsed(r):
 try:
  ts=float(r.get("AD"));
  if ts>10_000_000_000:ts/=1000.0
  mins=(time.time()-ts)/60.0
  return mins if -5<=mins<=180 else None
 except Exception:return None
def _absolute_minute(r):
 raw=r.get("BA");m=_num(raw);st=_status_text(r);elapsed=_kickoff_elapsed(r)
 if m is None:return None
 second_status=("2H" in st or "SECOND" in st or st.strip() in {"2","2ND"});second_elapsed=(elapsed is not None and elapsed>=55 and m<=45)
 if (second_status or second_elapsed) and m<=45:return m+45
 return m
def _live_events(rows):
 out=[]
 for r in rows:
  if str(r.get("AB") or "")!="2":continue
  eid=r.get("AA")
  if not eid:continue
  minute=_absolute_minute(r);status=r.get("AC") or r.get("BC") or "LIVE";elapsed=_kickoff_elapsed(r)
  out.append({"source":"flashscore","event_id":str(eid),"home":r.get("AE") or r.get("CX") or "","away":r.get("AF") or r.get("CX_2") or "","home_score":r.get("AG"),"away_score":r.get("AH"),"status":status,"start_ts":r.get("AD"),"live_flag":"2","minute":minute,"minute_raw":r.get("BA"),"elapsed_wall_min":round(elapsed,1) if elapsed is not None else None,"raw":{k:r[k] for k in list(r)[:32]}})
  if len(out)>=node.MAX_EVENTS:break
 return out
def _score_part(v):return "" if v is None or str(v).strip()=="" else str(v).strip()
def _base(event,bid,book,scope,line,side,odd,source,ts,market="TOTAL",market_raw="OVER_UNDER"):
 hs=_score_part(event.get("home_score"));aw=_score_part(event.get("away_score"));return {"event_id":event["event_id"],"home":event.get("home"),"away":event.get("away"),"score":f"{hs}:{aw}","score_live":f"{hs}:{aw}","minute":event.get("minute"),"minute_raw":event.get("minute_raw"),"status":event.get("status"),"bookmaker_id":bid,"bookmaker":book,"market":market,"market_raw":market_raw,"scope":scope,"line":line,"side":side,"odd":odd,"opening":None,"timestamp":ts,"source":source}
def _lsapp_rows(event,ts):
 if old_live is None:return []
 try:rows=old_live.fetch_live_odds(event["event_id"])
 except Exception as exc:node.LOG.info("OLD_LSAPP_FAIL event=%s %s",event["event_id"],type(exc).__name__);return []
 out=[]
 for row in rows or []:
  bid=row.get("bookmakerId");scope=str(row.get("bettingScope") or "FULL_TIME")
  for x in row.get("odds") or []:
   try:odd=float(x.get("value"));line=float((x.get("handicap") or {}).get("value"))
   except (TypeError,ValueError):continue
   side=str(x.get("selection") or "").upper()
   if side in {"OVER","UNDER"} and 1.01<odd<=12:out.append(_base(event,bid,f"lsapp_{bid}",scope,line,side,odd,"LIVE_OLE2",ts))
 return out
def _betb2b_rows(event,ts):
 if betb2b is None:return []
 try:
  k=betb2b._key(event.get("home"),event.get("away"))
  with betb2b._LOCK:mapped=(betb2b._EVENT_MAP.get(k) or {}).copy()
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
  preferred=[x for x in overs if x[0]==1] or overs;_,line,over=min(preferred,key=lambda x:abs(x[2]-2.0)+(abs(unders.get(x[1],5)-2.0) if x[1] in unders else 3));out=[_base(event,100000,"1xBet/BetB2B","FULL_TIME",line,"OVER",over,"BETB2B_1XBET",ts)];under=unders.get(line)
  if under and under>1:out.append(_base(event,100000,"1xBet/BetB2B","FULL_TIME",line,"UNDER",under,"BETB2B_1XBET",ts))
  return out
 except Exception:return []
def _kambi_rows(event,ts):
 if kambi is None:return []
 try:
  matched=kambi._find_event(event.get("home") or "",event.get("away") or "")
  if not matched:return []
  data=kambi._event_data(str(matched.get("id")));out=[];counts={"TOTAL":0,"1X2":0,"BTTS":0}
  for offer in data.get("betOffers") or []:
   type_name=str((offer.get("betOfferType") or {}).get("name") or "");criterion=str((offer.get("criterion") or {}).get("label") or "");key=f"{type_name} {criterion}".lower()
   if any(x in key for x in ("corner","card","shot","booking","player","team total")):continue
   scope=kambi._scope_from_offer(criterion,type_name)
   if scope not in {"FULL_TIME","FIRST_HALF","SECOND_HALF"}:continue
   kind=""
   if any(x in key for x in ("over/under","total goals")) and "asian" not in key and " by " not in key:kind="TOTAL"
   elif any(x in key for x in ("match result","full time result","1x2")):kind="1X2"
   elif any(x in key for x in ("both teams to score","both teams score","btts")):kind="BTTS"
   if not kind:continue
   for outcome in offer.get("outcomes") or []:
    if outcome.get("status")!="OPEN":continue
    label=str(outcome.get("label") or "").strip().lower();otype=str(outcome.get("type") or "").upper()
    try:odd=float(outcome.get("odds"))/1000.0
    except (TypeError,ValueError):continue
    if odd<=1.01:continue
    side="";line=None
    if kind=="TOTAL":
     side="OVER" if ("over" in label or otype=="OT_OVER") else "UNDER" if ("under" in label or otype=="OT_UNDER") else ""
     try:raw=outcome.get("line");line=float(raw)/1000.0 if raw is not None else None
     except (TypeError,ValueError):line=None
     if not side or line is None or not kambi._standard_line(line):continue
     out.append(_base(event,200000,"Kambi/BetRivers",scope,line,side,odd,"KAMBI",ts,"TOTAL","OVER_UNDER"));counts["TOTAL"]+=1
    elif kind=="1X2" and scope=="FULL_TIME":
     if otype in {"OT_ONE","OT_HOME"} or label in {"1","home",event.get("home","").lower()}:side="HOME"
     elif otype in {"OT_CROSS","OT_DRAW"} or label in {"x","draw","tie"}:side="DRAW"
     elif otype in {"OT_TWO","OT_AWAY"} or label in {"2","away",event.get("away","").lower()}:side="AWAY"
     if side and odd<=20:out.append(_base(event,200000,"Kambi/BetRivers",scope,None,side,odd,"KAMBI",ts,"1X2","HOME_DRAW_AWAY"));counts["1X2"]+=1
    elif kind=="BTTS" and scope=="FULL_TIME":
     if label in {"yes","y"} or otype in {"OT_YES","OT_TRUE"}:side="YES"
     elif label in {"no","n"} or otype in {"OT_NO","OT_FALSE"}:side="NO"
     if side and odd<=8:out.append(_base(event,200000,"Kambi/BetRivers",scope,None,side,odd,"KAMBI",ts,"BTTS","BOTH_TEAMS_TO_SCORE"));counts["BTTS"]+=1
  if out:node.LOG.info("KAMBI_LIVE_MARKETS %s - %s total=%d 1x2=%d btts=%d rows=%d",event.get("home"),event.get("away"),counts["TOTAL"],counts["1X2"],counts["BTTS"],len(out))
  return out
 except Exception as exc:node.LOG.info("KAMBI_MARKET_FAIL event=%s %s",event["event_id"],type(exc).__name__);return []
def _fetch_event_odds(lib,events):
 b2=0
 if betb2b is not None:
  try:b2=betb2b.sample_live(force=True)
  except Exception as exc:node.LOG.info("BETB2B_CYCLE_FAIL %s",type(exc).__name__)
 records=[];probes=[];ts=node._now_iso()
 for event in events[:node.MAX_ODDS_EVENTS]:
  a=_lsapp_rows(event,ts);b=_betb2b_rows(event,ts);c=_kambi_rows(event,ts);merged=a+b+c;records.extend(merged[:node.MAX_RECORDS_PER_EVENT]);totals=sum(1 for x in merged if x.get("market")=="TOTAL");x12=sum(1 for x in merged if x.get("market")=="1X2");btts=sum(1 for x in merged if x.get("market")=="BTTS")
  probes.append({"event_id":event["event_id"],"home":event.get("home"),"away":event.get("away"),"status":200,"ok":bool(merged),"records":len(merged),"entries":len(a),"source":"OLD_MULTI_PLUS_KAMBI","lsapp":len(a),"betb2b":len(b),"kambi":len(c),"total":totals,"1x2":x12,"btts":btts});node.LOG.info("LIVE_MARKETS event=%s total=%d 1x2=%d btts=%d records=%d",event["event_id"],totals,x12,btts,len(merged))
  if len(records)>=node.MAX_RECORDS:break
 node.LOG.info("LIVE_MARKET_CYCLE live=%d betb2b_priced=%d records=%d",len(events),b2,len(records));return node._apply_history(records[:node.MAX_RECORDS]),probes,[]
node._flash_events=_live_events;node._fetch_event_odds=_fetch_event_odds
if __name__=="__main__":node.LOG.info("GOOL_MARKET_LIVE TOTAL_OU + KAMBI_1X2 + KAMBI_BTTS for BEST_BET");node.main()
