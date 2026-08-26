"""Lightweight GOOL market node for Bot-Hosting.net (256 MB friendly).

Purpose: collect BetB2B/1xBet live goal-total prices and suspend/reopen state from
a second IP. No Telegram, PIL, analytics or database dependencies.

Env:
  PORT=3000 (or Bot-Hosting SERVER_PORT)
  MARKET_NODE_SECRET=<shared secret>
  MARKET_NODE_INTERVAL=20
  MARKET_NODE_MAX_EVENTS=80
"""
from __future__ import annotations
import json,logging,os,re,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import requests

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("market_node")
BASE="https://1xbet.fi/service-api"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9","Referer":"https://1xbet.fi/","Origin":"https://1xbet.fi"}
INTERVAL=max(12,int(os.getenv("MARKET_NODE_INTERVAL","20")))
MAX_EVENTS=max(10,min(120,int(os.getenv("MARKET_NODE_MAX_EVENTS","80"))))
SECRET=os.getenv("MARKET_NODE_SECRET","").strip()
PORT=int(os.getenv("PORT") or os.getenv("SERVER_PORT") or os.getenv("MARKET_NODE_PORT") or "3000")
LOCK=threading.Lock();STATE={};LAST_CYCLE=0.;LAST_ERROR="";CYCLES=0
SESSION=requests.Session();SESSION.headers.update(HEADERS)

def _norm(s):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).split())
def _key(h,a):return _norm(h)+"|"+_norm(a)
def _get(path,params):
 r=SESSION.get(BASE+path,params=params,timeout=10)
 r.raise_for_status();return (r.json() or {}).get("Value")
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

def _detail(event):
 eid=event.get("I");h=event.get("O1");a=event.get("O2")
 if not eid or not h or not a:return None
 d=_get("/LiveFeed/GetGameZip",{"id":eid,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2})
 if not isinstance(d,dict):return None
 return h,a,eid,_main_over(d)

def _apply(now,h,a,eid,market):
 k=_key(h,a)
 with LOCK:
  row=STATE.setdefault(k,{"home":h,"away":a,"event_id":eid,"points":[],"offered":False,"missing_since":None,"suspends":0,"reopens":0,"last_reopen_delta_pp":0.0,"last_odds":None,"updated":now})
  row.update({"home":h,"away":a,"event_id":eid,"updated":now})
  if market:
   line,odd=market
   if not row.get("offered") and row.get("missing_since") is not None:
    row["reopens"]=int(row.get("reopens",0))+1
    old=row.get("last_odds")
    if old and old>1 and odd>1:row["last_reopen_delta_pp"]=round((1/odd-1/old)*100,2)
   row["offered"]=True;row["missing_since"]=None;row["last_odds"]=odd
   pts=row.setdefault("points",[])
   if not pts or pts[-1][1]!=odd or pts[-1][2]!=line:pts.append([now,odd,line])
   row["points"]=[p for p in pts[-90:] if p[0]>=now-21600]
  elif row.get("offered"):
   row["offered"]=False;row["missing_since"]=now;row["suspends"]=int(row.get("suspends",0))+1

def collect_once():
 global LAST_CYCLE,LAST_ERROR,CYCLES
 now=time.time();priced=0
 try:
  events=_get("/LiveFeed/Get1x2_VZip",{"sports":1,"count":1000,"lng":"en","mode":4,"country":1,"getEmpty":"true"}) or []
  events=events[:MAX_EVENTS]
  with ThreadPoolExecutor(max_workers=6) as ex:
   fs=[ex.submit(_detail,e) for e in events]
   for f in as_completed(fs):
    try:r=f.result()
    except Exception:continue
    if not r:continue
    h,a,eid,market=r;_apply(now,h,a,eid,market);priced+=int(bool(market))
  with LOCK:
   cutoff=now-8*3600
   for k in list(STATE):
    if float(STATE[k].get("updated",0))<cutoff:STATE.pop(k,None)
  LAST_ERROR="";LAST_CYCLE=now;CYCLES+=1
  log.info("MARKET_NODE cycle=%d events=%d priced=%d state=%d",CYCLES,len(events),priced,len(STATE))
 except Exception as exc:
  LAST_ERROR=f"{type(exc).__name__}: {exc}";LAST_CYCLE=now;log.warning("MARKET_NODE_FAIL %s",LAST_ERROR)

def collector():
 while True:
  start=time.monotonic();collect_once();time.sleep(max(2,INTERVAL-(time.monotonic()-start)))

def _authorized(handler):
 if not SECRET:return True
 auth=handler.headers.get("Authorization","")
 return auth=="Bearer "+SECRET
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):return
 def _send(self,code,obj):
  raw=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path.startswith("/health"):
   self._send(200,{"ok":True,"cycles":CYCLES,"last_cycle":LAST_CYCLE,"last_error":LAST_ERROR,"events":len(STATE)});return
  if self.path.startswith("/snapshot"):
   if not _authorized(self):self._send(401,{"ok":False});return
   with LOCK:data={k:dict(v) for k,v in STATE.items()}
   self._send(200,{"ok":True,"ts":time.time(),"node":"bot-hosting","events":data});return
  self._send(404,{"ok":False})

def main():
 threading.Thread(target=collector,daemon=True).start();srv=ThreadingHTTPServer(("0.0.0.0",PORT),Handler);log.info("MARKET_NODE_HTTP port=%d interval=%ds max_events=%d",PORT,INTERVAL,MAX_EVENTS);srv.serve_forever()
if __name__=="__main__":main()
