"""Lightweight GOOL market node for Bot-Hosting.net (256 MB friendly).

Collects BetB2B/1xBet live prices from a second IP, all priced live selections,
and today's prematch football fixture list. No Telegram/PIL/heavy analytics.
"""
from __future__ import annotations
import json,logging,os,re,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from zoneinfo import ZoneInfo
import requests

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("market_node")
BASE="https://1xbet.fi/service-api"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9","Referer":"https://1xbet.fi/","Origin":"https://1xbet.fi"}
INTERVAL=max(12,int(os.getenv("MARKET_NODE_INTERVAL","20")))
PREMATCH_INTERVAL=max(300,int(os.getenv("MARKET_NODE_PREMATCH_INTERVAL","900")))
MAX_EVENTS=max(10,min(120,int(os.getenv("MARKET_NODE_MAX_EVENTS","80"))))
MAX_MARKETS_PER_EVENT=max(40,min(500,int(os.getenv("MARKET_NODE_MAX_MARKETS_PER_EVENT","250"))))
SECRET=os.getenv("MARKET_NODE_SECRET","").strip()
PORT=int(os.getenv("PORT") or os.getenv("SERVER_PORT") or os.getenv("MARKET_NODE_PORT") or "3000")
TZ=ZoneInfo(os.getenv("MARKET_NODE_TZ","Europe/Moscow"))
LOCK=threading.Lock();STATE={};FIXTURES={};LAST_CYCLE=0.;LAST_ERROR="";CYCLES=0;LAST_PREMATCH=0.;PREMATCH_ERROR=""
SESSION=requests.Session();SESSION.headers.update(HEADERS)

def _norm(s):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).split())
def _key(h,a):return _norm(h)+"|"+_norm(a)
def _get(path,params):
 r=SESSION.get(BASE+path,params=params,timeout=10);r.raise_for_status();return (r.json() or {}).get("Value")
def _txt(obj,*keys):
 for k in keys:
  v=obj.get(k)
  if isinstance(v,str) and v.strip():return v.strip()
 return ""
def _main_over(event):
 overs=[];unders={}
 for group in event.get("GE") or []:
  try:g=int(group.get("G") or -1)
  except Exception:continue
  if g!=4:continue
  for bucket in group.get("E") or []:
   for row in bucket or []:
    try:t=int(row.get("T"));line=float(row.get("P"));odd=float(row.get("C"))
    except Exception:continue
    if odd<=1:continue
    if t==9:overs.append(row)
    elif t==10:unders[line]=odd
 if not overs:return None
 preferred=[x for x in overs if int(x.get("CE") or 0)==1]
 if preferred:
  x=preferred[0];return float(x["P"]),float(x["C"])
 scored=[]
 for x in overs:
  line=float(x["P"]);odd=float(x["C"]);u=unders.get(line);scored.append((abs(odd-2)+(abs(u-2) if u else 3),line,odd))
 _,line,odd=min(scored);return line,odd

def _all_markets(event):
 out=[];period=_txt(event,"PN","PeriodName") or str(event.get("P") or "FT")
 for group in event.get("GE") or []:
  gid=group.get("G");gname=_txt(group,"GN","N","Name")
  for bucket_i,bucket in enumerate(group.get("E") or []):
   for row_i,row in enumerate(bucket or []):
    try:odd=float(row.get("C"))
    except Exception:continue
    if odd<=1:continue
    tid=row.get("T");line=row.get("P")
    try:line=None if line is None else float(line)
    except Exception:line=None
    name=_txt(row,"N","Name","SN","SelectionName");sel_id=row.get("I") or row.get("ID") or row.get("E") or row.get("PL") or f"{bucket_i}:{row_i}"
    mkey=f"{period}|G{gid}|T{tid}|P{line}|S{sel_id}"
    out.append({"key":mkey,"period":period,"group_id":gid,"group":gname,"type_id":tid,"name":name,"line":line,"odds":odd})
    if len(out)>=MAX_MARKETS_PER_EVENT:return out
 return out

def _detail(event):
 eid=event.get("I");h=event.get("O1");a=event.get("O2")
 if not eid or not h or not a:return None
 d=_get("/LiveFeed/GetGameZip",{"id":eid,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2})
 if not isinstance(d,dict):return None
 return h,a,eid,_main_over(d),_all_markets(d)

def _update_selection(sel,now,item):
 old_offered=bool(sel.get("offered"));old_odds=sel.get("last_odds")
 if not old_offered and sel.get("missing_since") is not None:
  sel["reopens"]=int(sel.get("reopens",0))+1
  if old_odds and old_odds>1 and item["odds"]>1:sel["last_reopen_delta_pp"]=round((1/item["odds"]-1/old_odds)*100,2)
 sel.update({"offered":True,"missing_since":None,"last_odds":item["odds"],"line":item.get("line"),"period":item.get("period"),"group_id":item.get("group_id"),"group":item.get("group"),"type_id":item.get("type_id"),"name":item.get("name"),"updated":now})
 pts=sel.setdefault("points",[])
 if not pts or pts[-1][1]!=item["odds"] or pts[-1][2]!=item.get("line"):pts.append([now,item["odds"],item.get("line")])
 sel["points"]=[p for p in pts[-90:] if p[0]>=now-21600]

def _apply(now,h,a,eid,main_market,markets):
 k=_key(h,a)
 with LOCK:
  row=STATE.setdefault(k,{"home":h,"away":a,"event_id":eid,"points":[],"offered":False,"missing_since":None,"suspends":0,"reopens":0,"last_reopen_delta_pp":0.0,"last_odds":None,"markets":{},"updated":now})
  row.update({"home":h,"away":a,"event_id":eid,"updated":now})
  if main_market:
   line,odd=main_market
   if not row.get("offered") and row.get("missing_since") is not None:
    row["reopens"]=int(row.get("reopens",0))+1;old=row.get("last_odds")
    if old and old>1 and odd>1:row["last_reopen_delta_pp"]=round((1/odd-1/old)*100,2)
   row["offered"]=True;row["missing_since"]=None;row["last_odds"]=odd
   pts=row.setdefault("points",[])
   if not pts or pts[-1][1]!=odd or pts[-1][2]!=line:pts.append([now,odd,line])
   row["points"]=[p for p in pts[-90:] if p[0]>=now-21600]
  elif row.get("offered"):
   row["offered"]=False;row["missing_since"]=now;row["suspends"]=int(row.get("suspends",0))+1
  book=row.setdefault("markets",{});seen=set()
  for item in markets:
   mk=item["key"];seen.add(mk);sel=book.setdefault(mk,{"points":[],"offered":False,"missing_since":None,"suspends":0,"reopens":0,"last_reopen_delta_pp":0.0,"last_odds":None});_update_selection(sel,now,item)
  for mk,sel in book.items():
   if mk not in seen and sel.get("offered"):
    sel["offered"]=False;sel["missing_since"]=now;sel["suspends"]=int(sel.get("suspends",0))+1;sel["updated"]=now
  for mk in [mk for mk,sel in book.items() if float(sel.get("updated",0) or 0)<now-21600]:book.pop(mk,None)

def collect_once():
 global LAST_CYCLE,LAST_ERROR,CYCLES
 now=time.time();priced=0;selections=0
 try:
  events=_get("/LiveFeed/Get1x2_VZip",{"sports":1,"count":1000,"lng":"en","mode":4,"country":1,"getEmpty":"true"}) or [];events=events[:MAX_EVENTS]
  with ThreadPoolExecutor(max_workers=6) as ex:
   fs=[ex.submit(_detail,e) for e in events]
   for f in as_completed(fs):
    try:r=f.result()
    except Exception:continue
    if not r:continue
    h,a,eid,main_market,markets=r;_apply(now,h,a,eid,main_market,markets);priced+=int(bool(main_market));selections+=len(markets)
  with LOCK:
   cutoff=now-8*3600
   for k in list(STATE):
    if float(STATE[k].get("updated",0))<cutoff:STATE.pop(k,None)
  LAST_ERROR="";LAST_CYCLE=now;CYCLES+=1
  log.info("MARKET_NODE cycle=%d events=%d priced=%d selections=%d state=%d",CYCLES,len(events),priced,selections,len(STATE))
 except Exception as exc:
  LAST_ERROR=f"{type(exc).__name__}: {exc}";LAST_CYCLE=now;log.warning("MARKET_NODE_FAIL %s",LAST_ERROR)

def collect_prematch_once():
 global LAST_PREMATCH,PREMATCH_ERROR
 try:
  events=_get("/LineFeed/Get1x2_VZip",{"sports":1,"count":1000,"lng":"en","mode":4,"country":1,"getEmpty":"true"}) or []
  today=datetime.now(TZ).date();out={}
  for e in events:
   try:start=float(e.get("S"))
   except Exception:continue
   dt=datetime.fromtimestamp(start,TZ)
   if dt.date()!=today:continue
   eid=e.get("I");h=e.get("O1");a=e.get("O2")
   if not eid or not h or not a:continue
   out[str(eid)]={"event_id":eid,"home":h,"away":a,"league":e.get("L") or e.get("LE") or "","country":e.get("CN") or e.get("CO") or "","start_ts":start,"start_local":dt.isoformat(timespec="minutes")}
  with LOCK:
   FIXTURES.clear();FIXTURES.update(out)
  LAST_PREMATCH=time.time();PREMATCH_ERROR="";log.info("PREMATCH_TODAY fixtures=%d date=%s",len(out),today.isoformat())
  return len(out)
 except Exception as exc:
  PREMATCH_ERROR=f"{type(exc).__name__}: {exc}";LAST_PREMATCH=time.time();log.warning("PREMATCH_TODAY_FAIL %s",PREMATCH_ERROR);return 0

def collector():
 while True:
  start=time.monotonic();collect_once();time.sleep(max(2,INTERVAL-(time.monotonic()-start)))
def prematch_collector():
 while True:
  start=time.monotonic();collect_prematch_once();time.sleep(max(30,PREMATCH_INTERVAL-(time.monotonic()-start)))
def _authorized(handler):
 if not SECRET:return True
 return handler.headers.get("Authorization","")=="Bearer "+SECRET
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):return
 def _send(self,code,obj):
  raw=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path.startswith("/health"):
   with LOCK:market_count=sum(len((r.get("markets") or {})) for r in STATE.values());fixtures=len(FIXTURES)
   self._send(200,{"ok":True,"cycles":CYCLES,"last_cycle":LAST_CYCLE,"last_error":LAST_ERROR,"events":len(STATE),"markets":market_count,"fixtures_today":fixtures,"last_prematch":LAST_PREMATCH,"prematch_error":PREMATCH_ERROR});return
  if self.path.startswith("/fixtures/today"):
   if not _authorized(self):self._send(401,{"ok":False});return
   with LOCK:data=sorted((dict(v) for v in FIXTURES.values()),key=lambda x:x.get("start_ts",0))
   self._send(200,{"ok":True,"ts":time.time(),"timezone":str(TZ),"count":len(data),"fixtures":data});return
  if self.path.startswith("/snapshot"):
   if not _authorized(self):self._send(401,{"ok":False});return
   with LOCK:data={k:dict(v) for k,v in STATE.items()};fixtures={k:dict(v) for k,v in FIXTURES.items()}
   self._send(200,{"ok":True,"ts":time.time(),"node":"bot-hosting","events":data,"fixtures_today":fixtures});return
  self._send(404,{"ok":False})
def main():
 threading.Thread(target=collector,daemon=True).start();threading.Thread(target=prematch_collector,daemon=True).start();srv=ThreadingHTTPServer(("0.0.0.0",PORT),Handler);log.info("MARKET_NODE_HTTP port=%d interval=%ds prematch=%ds max_events=%d all_markets=%d",PORT,INTERVAL,PREMATCH_INTERVAL,MAX_EVENTS,MAX_MARKETS_PER_EVENT);srv.serve_forever()
if __name__=="__main__":main()
