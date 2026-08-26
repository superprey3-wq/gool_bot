"""Lightweight GOOL market node for Bot-Hosting.net (256 MB friendly).

Collects BetB2B/1xBet live prices from a second IP, all priced live selections,
and today's prematch football fixture list. Heavy all-market history stays on
this node; the main GOOL server only pulls compact snapshots/anomalies.
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
    out.append({"key":f"{period}|G{gid}|T{tid}|P{line}|S{sel_id}","period":period,"group_id":gid,"group":gname,"type_id":tid,"name":name,"line":line,"odds":odd})
    if len(out)>=MAX_MARKETS_PER_EVENT:return out
 return out

def _detail(event):
 eid=event.get("I");h=event.get("O1");a=event.get("O2")
 if not eid or not h or not a:return None
 d=_get("/LiveFeed/GetGameZip",{"id":eid,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2})
 if not isinstance(d,dict):return None
 return h,a,eid,_main_over(d),_all_markets(d)

def _update_selection(sel,now,item):
 old_odds=sel.get("last_odds")
 if not sel.get("offered") and sel.get("missing_since") is not None:
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
  with LOCK:FIXTURES.clear();FIXTURES.update(out)
  LAST_PREMATCH=time.time();PREMATCH_ERROR="";log.info("PREMATCH_TODAY fixtures=%d date=%s",len(out),today.isoformat());return len(out)
 except Exception as exc:
  PREMATCH_ERROR=f"{type(exc).__name__}: {exc}";LAST_PREMATCH=time.time();log.warning("PREMATCH_TODAY_FAIL %s",PREMATCH_ERROR);return 0

def _compact_events():
 out={}
 for k,row in STATE.items():
  out[k]={x:row.get(x) for x in ("home","away","event_id","points","offered","missing_since","suspends","reopens","last_reopen_delta_pp","last_odds","updated")}
 return out

def _label(sel):
 name=str(sel.get("name") or "").strip();group=str(sel.get("group") or "").strip();period=str(sel.get("period") or "").strip();line=sel.get("line")
 base=name or group or f"G{sel.get('group_id')} / T{sel.get('type_id')}"
 if isinstance(line,(int,float)) and str(line) not in base:base=f"{base} {line:g}"
 return f"{period} · {base}" if period and period not in {"FT","0"} else base

def _anomalies(now=None):
 now=now or time.time();out=[]
 for event_key,row in STATE.items():
  best=None
  for market_key,sel in (row.get("markets") or {}).items():
   pts=[]
   for raw in sel.get("points") or []:
    try:ts=float(raw[0]);odd=float(raw[1]);line=None if raw[2] is None else float(raw[2])
    except Exception:continue
    if odd>1 and ts>=now-600:pts.append([ts,odd,line])
   if len(pts)<2:continue
   first,last=pts[0],pts[-1];elapsed=max(1.,last[0]-first[0]);delta=(1/last[1]-1/first[1])*100;line_move=0.0
   if first[2] is not None and last[2] is not None:line_move=last[2]-first[2]
   susp=int(sel.get("suspends",0) or 0);reop=int(sel.get("reopens",0) or 0);rd=float(sel.get("last_reopen_delta_pp",0) or 0);score=0
   if abs(delta)>=5:score+=2
   elif abs(delta)>=3:score+=1
   if abs(delta)>=3 and elapsed<=180:score+=1
   if abs(line_move)>=0.25:score+=1
   if susp>=1 and reop>=1:score+=1
   if susp>=2:score+=1
   if abs(rd)>=1.5:score+=1
   if score<3 or (abs(delta)<3 and abs(rd)<1.5 and abs(line_move)<0.25):continue
   sig={"key":event_key,"market_key":market_key,"home":row.get("home") or "?","away":row.get("away") or "?","event_id":row.get("event_id"),"market":_label(sel),"score":score,"delta_pp":round(delta,2),"elapsed":int(elapsed),"start_odds":round(first[1],3),"last_odds":round(last[1],3),"start_line":first[2],"last_line":last[2],"line_move":round(line_move,2),"suspends":susp,"reopens":reop,"reopen_delta_pp":round(rd,2),"fingerprint":f"{market_key}:{round(last[1],3)}:{last[2]}:{susp}:{reop}","created_ts":now}
   if best is None or (sig["score"],abs(sig["delta_pp"]),abs(sig["reopen_delta_pp"]),abs(sig["line_move"]))>(best["score"],abs(best["delta_pp"]),abs(best["reopen_delta_pp"]),abs(best["line_move"])):best=sig
  if best:out.append(best)
 return out[:80]

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
  if self.path.startswith("/anomalies"):
   if not _authorized(self):self._send(401,{"ok":False});return
   with LOCK:data=_anomalies()
   self._send(200,{"ok":True,"ts":time.time(),"count":len(data),"signals":data});return
  if self.path.startswith("/snapshot"):
   if not _authorized(self):self._send(401,{"ok":False});return
   with LOCK:data=_compact_events()
   self._send(200,{"ok":True,"ts":time.time(),"node":"bot-hosting","events":data});return
  self._send(404,{"ok":False})
def main():
 threading.Thread(target=collector,daemon=True).start();threading.Thread(target=prematch_collector,daemon=True).start();srv=ThreadingHTTPServer(("0.0.0.0",PORT),Handler);log.info("MARKET_NODE_HTTP port=%d interval=%ds prematch=%ds max_events=%d all_markets=%d compact_api=1",PORT,INTERVAL,PREMATCH_INTERVAL,MAX_EVENTS,MAX_MARKETS_PER_EVENT);srv.serve_forever()
if __name__=="__main__":main()
