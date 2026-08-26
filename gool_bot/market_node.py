"""GOOL lightweight secondary market node: Flashscore day/live gated + selected markets only."""
from __future__ import annotations
import json,logging,os,re,threading,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from zoneinfo import ZoneInfo
import requests

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
log=logging.getLogger("market_node")
BASE="https://1xbet.fi/service-api"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9","Referer":"https://1xbet.fi/","Origin":"https://1xbet.fi"}
FS_URL=os.getenv("MARKET_NODE_FLASHSCORE_URL","https://local-global.flashscore.ninja/2/x/feed/f_1_0_3_en_1")
FS_HEADERS={"User-Agent":"Mozilla/5.0","Accept":"*/*","Accept-Language":"en","Referer":"https://www.flashscore.com/","Origin":"https://www.flashscore.com","x-fsign":"SW9D1eZo"}
INTERVAL=max(12,int(os.getenv("MARKET_NODE_INTERVAL","20")))
FS_INTERVAL=max(30,int(os.getenv("MARKET_NODE_FS_INTERVAL","60")))
PREMATCH_INTERVAL=max(300,int(os.getenv("MARKET_NODE_PREMATCH_INTERVAL","900")))
MAX_EVENTS=max(10,min(120,int(os.getenv("MARKET_NODE_MAX_EVENTS","80"))))
MAX_MARKETS_PER_EVENT=max(20,min(180,int(os.getenv("MARKET_NODE_MAX_MARKETS_PER_EVENT","100"))))
SECRET=os.getenv("MARKET_NODE_SECRET","").strip()
PORT=int(os.getenv("PORT") or os.getenv("SERVER_PORT") or os.getenv("MARKET_NODE_PORT") or "3000")
TZ=ZoneInfo(os.getenv("MARKET_NODE_TZ","Europe/Moscow"))
LOCK=threading.Lock();STATE={};FIXTURES={};FS_MATCHES={};LAST_CYCLE=0.;LAST_ERROR="";CYCLES=0;LAST_PREMATCH=0.;PREMATCH_ERROR="";LAST_FS=0.;FS_ERROR=""
SESSION=requests.Session();SESSION.headers.update(HEADERS)
FS_SESSION=requests.Session();FS_SESSION.headers.update(FS_HEADERS)

def _norm(s):
 s=str(s or "").lower();s=re.sub(r"\b(fc|cf|sc|afc|fk|club|women|w)\b"," ",s);return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())
def _key(h,a):return _norm(h)+"|"+_norm(a)
def _sim(a,b):
 a,b=_norm(a),_norm(b)
 if not a or not b:return 0.
 if a==b:return 1.
 if a in b or b in a:return .92
 return SequenceMatcher(None,a,b).ratio()
def _get(path,params):
 r=SESSION.get(BASE+path,params=params,timeout=10);r.raise_for_status();return (r.json() or {}).get("Value")
def _txt(obj,*keys):
 for k in keys:
  v=obj.get(k)
  if isinstance(v,str) and v.strip():return v.strip()
 return ""
def _parse_fs_feed(text):
 rows=[];cur={}
 for part in text.split("¬"):
  if "÷" not in part:continue
  k,v=part.split("÷",1);k=k[1:] if k.startswith("~") else k
  if k=="AA":
   if cur.get("AA"):rows.append(cur)
   cur={"AA":v}
  elif cur:cur[k]=v
 if cur.get("AA"):rows.append(cur)
 out={};today=datetime.now(TZ).date()
 for x in rows:
  h=x.get("AE");a=x.get("AF")
  if not h or not a:continue
  try:ts=float(x.get("AD") or 0)
  except Exception:ts=0.
  status=str(x.get("AB","") or "")
  if ts:
   try:local_date=datetime.fromtimestamp(ts,TZ).date()
   except Exception:local_date=today
   if local_date!=today and status!="2":continue
  out[x["AA"]]={"fs_id":x["AA"],"home":h,"away":a,"start_ts":ts,"status":status,"minute":x.get("BA","") or "","period":x.get("BC","") or "","league":x.get("ZA","") or x.get("AC","") or ""}
 return out
def refresh_flashscore():
 global LAST_FS,FS_ERROR
 try:
  r=FS_SESSION.get(FS_URL,timeout=12);r.raise_for_status();data=_parse_fs_feed(r.text)
  if not data:raise RuntimeError("empty Flashscore feed")
  live=sum(1 for f in data.values() if str(f.get("status"))=="2")
  with LOCK:FS_MATCHES.clear();FS_MATCHES.update(data)
  LAST_FS=time.time();FS_ERROR="";log.info("FLASHSCORE_TODAY matches=%d live=%d",len(data),live);return len(data)
 except Exception as exc:
  LAST_FS=time.time();FS_ERROR=f"{type(exc).__name__}: {exc}";log.warning("FLASHSCORE_FAIL %s",FS_ERROR);return 0
def _fs_match(h,a,start_ts=0,live_only=True):
 with LOCK:vals=list(FS_MATCHES.values())
 best=None;bestscore=0.
 for f in vals:
  if live_only and str(f.get("status"))!="2":continue
  score=max((_sim(h,f["home"])+_sim(a,f["away"]))/2,(_sim(h,f["away"])+_sim(a,f["home"]))/2)
  if score<.72:continue
  if start_ts and f.get("start_ts") and abs(float(start_ts)-float(f["start_ts"]))>4*3600:continue
  if score>bestscore:best,bestscore=f,score
 return best if bestscore>=.72 else None
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
 preferred=[x for x in overs if int(x.get("CE") or 0)==1];x=preferred[0] if preferred else min(overs,key=lambda z:abs(float(z["C"])-2)+(abs(unders.get(float(z["P"]),5)-2)))
 return float(x["P"]),float(x["C"])
def _wanted_market(group,row,period):
 gid=group.get("G");tid=row.get("T");g=_norm(_txt(group,"GN","N","Name"));n=_norm(_txt(row,"N","Name","SN","SelectionName"));s=f"{g} {n}";p=_norm(period)
 if p and not any(x in p for x in ("ft","match","1st","first","1 half","1h","2nd","second","2 half","2h","0","1","2")):return False
 if any(x in s for x in ("corner","card","booking","offside","throw in","shot","goal kick","exact score","correct score","next goal","penalty","substitution","both teams","btts","double chance","draw no bet")):return False
 if any(x in s for x in ("team total","individual total")):return True
 if any(x in s for x in ("handicap","spread")):return True
 if any(x in s for x in ("total","over","under")):return True
 if any(x in s for x in ("1x2","match result","winner","result","moneyline")):
  if any(x in n for x in ("draw","tie")) or n.strip()=="x":return False
  return True
 try:t=int(tid)
 except Exception:t=-999
 try:gidi=int(gid)
 except Exception:gidi=-999
 if gidi==1 and t in (1,3):return True
 if gidi in (2,3) and t in (7,8):return True
 if t in (9,10,11,12,13,14):return True
 return False
def _selected_markets(event):
 out=[];period=_txt(event,"PN","PeriodName") or str(event.get("P") or "FT")
 for group in event.get("GE") or []:
  gid=group.get("G");gname=_txt(group,"GN","N","Name")
  for bi,bucket in enumerate(group.get("E") or []):
   for ri,row in enumerate(bucket or []):
    try:odd=float(row.get("C"))
    except Exception:continue
    if odd<=1 or not _wanted_market(group,row,period):continue
    tid=row.get("T");line=row.get("P")
    try:line=None if line is None else float(line)
    except Exception:line=None
    name=_txt(row,"N","Name","SN","SelectionName");sid=row.get("I") or row.get("ID") or row.get("E") or row.get("PL") or f"{bi}:{ri}"
    out.append({"key":f"{period}|G{gid}|T{tid}|P{line}|S{sid}","period":period,"group_id":gid,"group":gname,"type_id":tid,"name":name,"line":line,"odds":odd})
    if len(out)>=MAX_MARKETS_PER_EVENT:return out
 return out
def _detail(event):
 eid=event.get("I");h=event.get("O1");a=event.get("O2")
 if not eid or not h or not a:return None
 try:start=float(event.get("S") or 0)
 except Exception:start=0.
 fs=_fs_match(h,a,start,live_only=True)
 if not fs:return None
 d=_get("/LiveFeed/GetGameZip",{"id":eid,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2})
 if not isinstance(d,dict):return None
 return h,a,eid,fs,_main_over(d),_selected_markets(d)
def _update_selection(sel,now,item):
 old=sel.get("last_odds")
 if not sel.get("offered") and sel.get("missing_since") is not None:
  sel["reopens"]=int(sel.get("reopens",0))+1
  if old and old>1 and item["odds"]>1:sel["last_reopen_delta_pp"]=round((1/item["odds"]-1/old)*100,2)
 sel.update({"offered":True,"missing_since":None,"last_odds":item["odds"],"line":item.get("line"),"period":item.get("period"),"group_id":item.get("group_id"),"group":item.get("group"),"type_id":item.get("type_id"),"name":item.get("name"),"updated":now})
 pts=sel.setdefault("points",[])
 if not pts or pts[-1][1]!=item["odds"] or pts[-1][2]!=item.get("line"):pts.append([now,item["odds"],item.get("line")])
 sel["points"]=[p for p in pts[-90:] if p[0]>=now-21600]
def _apply(now,h,a,eid,fs,main,markets):
 k=_key(h,a)
 with LOCK:
  row=STATE.setdefault(k,{"home":h,"away":a,"event_id":eid,"points":[],"offered":False,"missing_since":None,"suspends":0,"reopens":0,"last_reopen_delta_pp":0.0,"last_odds":None,"markets":{},"updated":now})
  row.update({"home":h,"away":a,"event_id":eid,"fs_id":fs.get("fs_id"),"fs_status":fs.get("status"),"fs_minute":fs.get("minute"),"fs_period":fs.get("period"),"updated":now})
  if main:
   line,odd=main
   if not row.get("offered") and row.get("missing_since") is not None:
    row["reopens"]=int(row.get("reopens",0))+1;old=row.get("last_odds")
    if old and old>1:row["last_reopen_delta_pp"]=round((1/odd-1/old)*100,2)
   row["offered"]=True;row["missing_since"]=None;row["last_odds"]=odd;pts=row.setdefault("points",[])
   if not pts or pts[-1][1]!=odd or pts[-1][2]!=line:pts.append([now,odd,line])
   row["points"]=[p for p in pts[-90:] if p[0]>=now-21600]
  book=row.setdefault("markets",{});seen=set()
  for item in markets:
   mk=item["key"];seen.add(mk);sel=book.setdefault(mk,{"points":[],"offered":False,"missing_since":None,"suspends":0,"reopens":0,"last_reopen_delta_pp":0.0,"last_odds":None});_update_selection(sel,now,item)
  for mk,sel in book.items():
   if mk not in seen and sel.get("offered"):sel["offered"]=False;sel["missing_since"]=now;sel["suspends"]=int(sel.get("suspends",0))+1;sel["updated"]=now
  for mk in [m for m,s in book.items() if float(s.get("updated",0) or 0)<now-21600]:book.pop(mk,None)
def collect_once():
 global LAST_CYCLE,LAST_ERROR,CYCLES
 now=time.time();priced=0;selections=0;matched=0
 try:
  if not FS_MATCHES or time.time()-LAST_FS>FS_INTERVAL:refresh_flashscore()
  if not FS_MATCHES or time.time()-LAST_FS>max(FS_INTERVAL*3,180):raise RuntimeError("Flashscore gate unavailable/stale")
  events=(_get("/LiveFeed/Get1x2_VZip",{"sports":1,"count":1000,"lng":"en","mode":4,"country":1,"getEmpty":"true"}) or [])[:MAX_EVENTS]
  with ThreadPoolExecutor(max_workers=5) as ex:
   fs=[ex.submit(_detail,e) for e in events]
   for f in as_completed(fs):
    try:r=f.result()
    except Exception:continue
    if not r:continue
    h,a,eid,fsm,main,markets=r;_apply(now,h,a,eid,fsm,main,markets);matched+=1;priced+=int(bool(main));selections+=len(markets)
  with LOCK:
   cutoff=now-8*3600
   for k in list(STATE):
    if float(STATE[k].get("updated",0))<cutoff:STATE.pop(k,None)
   live=sum(1 for f in FS_MATCHES.values() if str(f.get("status"))=="2")
  LAST_ERROR="";LAST_CYCLE=now;CYCLES+=1;log.info("MARKET_NODE cycle=%d book_events=%d fs_today=%d fs_live=%d matched_live=%d priced=%d selected_markets=%d state=%d",CYCLES,len(events),len(FS_MATCHES),live,matched,priced,selections,len(STATE))
 except Exception as exc:
  LAST_ERROR=f"{type(exc).__name__}: {exc}";LAST_CYCLE=now;log.warning("MARKET_NODE_FAIL %s",LAST_ERROR)
def collect_prematch_once():
 global LAST_PREMATCH,PREMATCH_ERROR
 try:
  if not FS_MATCHES:refresh_flashscore()
  today=datetime.now(TZ).date();out={}
  with LOCK:fsvals=list(FS_MATCHES.values())
  for f in fsvals:
   ts=float(f.get("start_ts") or 0)
   if ts and datetime.fromtimestamp(ts,TZ).date()!=today and str(f.get("status"))!="2":continue
   out[str(f["fs_id"])]={"event_id":f["fs_id"],"home":f["home"],"away":f["away"],"league":f.get("league") or "","country":"","start_ts":ts,"start_local":datetime.fromtimestamp(ts,TZ).isoformat(timespec="minutes") if ts else "","status":f.get("status") or "","minute":f.get("minute") or "","period":f.get("period") or "","source":"flashscore"}
  with LOCK:FIXTURES.clear();FIXTURES.update(out)
  LAST_PREMATCH=time.time();PREMATCH_ERROR="";live=sum(1 for f in out.values() if str(f.get("status"))=="2");log.info("PREMATCH_TODAY flashscore_fixtures=%d live=%d date=%s",len(out),live,today.isoformat());return len(out)
 except Exception as exc:
  PREMATCH_ERROR=f"{type(exc).__name__}: {exc}";LAST_PREMATCH=time.time();log.warning("PREMATCH_TODAY_FAIL %s",PREMATCH_ERROR);return 0
def _label(sel):
 name=str(sel.get("name") or "").strip();group=str(sel.get("group") or "").strip();period=str(sel.get("period") or "").strip();line=sel.get("line");base=name or group or f"G{sel.get('group_id')} / T{sel.get('type_id')}"
 if isinstance(line,(int,float)) and str(line) not in base:base=f"{base} {line:g}"
 return f"{period} · {base}" if period and period not in {"FT","0"} else base
def _best_market_signal(row,now=None):
 now=now or time.time();best=None
 for mk,sel in (row.get("markets") or {}).items():
  pts=[]
  for raw in sel.get("points") or []:
   try:ts=float(raw[0]);odd=float(raw[1]);line=None if raw[2] is None else float(raw[2])
   except Exception:continue
   if odd>1 and ts>=now-600:pts.append([ts,odd,line])
  if len(pts)<2:continue
  first,last=pts[0],pts[-1];elapsed=max(1.,last[0]-first[0]);delta=(1/last[1]-1/first[1])*100;lm=0.
  if first[2] is not None and last[2] is not None:lm=last[2]-first[2]
  susp=int(sel.get("suspends",0) or 0);reop=int(sel.get("reopens",0) or 0);rd=float(sel.get("last_reopen_delta_pp",0) or 0)
  purple=abs(delta)>=4 or (susp>=2 and abs(rd)>=1.5) or (susp>=1 and reop>=1 and abs(rd)>=3)
  if purple:dot="🟣"
  elif abs(delta)<1.5:dot="🟡"
  elif delta>0:dot="🟢"
  else:dot="🔴"
  strength=abs(delta)+min(2.,abs(lm)*2.)+min(2.,susp*.5+reop*.5)+min(2.,abs(rd)*.35)+(3. if purple else 0.)
  sig={"market_key":mk,"market":_label(sel),"dot":dot,"delta_pp":round(delta,2),"elapsed":int(elapsed),"line_move":round(lm,2),"suspends":susp,"reopens":reop,"reopen_delta_pp":round(rd,2),"points":pts[-12:],"last_odds":last[1],"last_line":last[2],"updated":last[0],"strength":round(strength,2)}
  if best is None or (sig["strength"],abs(sig["delta_pp"]),sig["updated"])>(best["strength"],abs(best["delta_pp"]),best["updated"]):best=sig
 return best
def _compact_events():
 now=time.time();out={}
 for k,r in STATE.items():
  best=_best_market_signal(r,now)
  row={x:r.get(x) for x in ("home","away","event_id","fs_id","fs_status","fs_minute","fs_period","updated")}
  if best:
   row.update({"points":best["points"],"offered":True,"missing_since":None,"suspends":best["suspends"],"reopens":best["reopens"],"last_reopen_delta_pp":best["reopen_delta_pp"],"last_odds":best["last_odds"],"best_market":best["market"],"best_market_key":best["market_key"],"market_dot":best["dot"],"market_delta_pp":best["delta_pp"],"market_strength":best["strength"],"market_elapsed":best["elapsed"],"market_line_move":best["line_move"]})
  else:
   row.update({"points":[],"offered":False,"missing_since":None,"suspends":0,"reopens":0,"last_reopen_delta_pp":0.0,"last_odds":None,"best_market":"","best_market_key":"","market_dot":"🟡","market_delta_pp":0.0,"market_strength":0.0,"market_elapsed":0,"market_line_move":0.0})
  out[k]=row
 return out
def _anomalies(now=None):
 now=now or time.time();out=[]
 for ek,row in STATE.items():
  best=None
  for mk,sel in (row.get("markets") or {}).items():
   pts=[]
   for raw in sel.get("points") or []:
    try:ts=float(raw[0]);odd=float(raw[1]);line=None if raw[2] is None else float(raw[2])
    except Exception:continue
    if odd>1 and ts>=now-600:pts.append([ts,odd,line])
   if len(pts)<2:continue
   first,last=pts[0],pts[-1];elapsed=max(1.,last[0]-first[0]);delta=(1/last[1]-1/first[1])*100;lm=0.
   if first[2] is not None and last[2] is not None:lm=last[2]-first[2]
   susp=int(sel.get("suspends",0) or 0);reop=int(sel.get("reopens",0) or 0);rd=float(sel.get("last_reopen_delta_pp",0) or 0);score=0
   if abs(delta)>=5:score+=2
   elif abs(delta)>=3:score+=1
   if abs(delta)>=3 and elapsed<=180:score+=1
   if abs(lm)>=.25:score+=1
   if susp>=1 and reop>=1:score+=1
   if susp>=2:score+=1
   if abs(rd)>=1.5:score+=1
   if score<3 or (abs(delta)<3 and abs(rd)<1.5 and abs(lm)<.25):continue
   sig={"key":ek,"market_key":mk,"home":row.get("home") or "?","away":row.get("away") or "?","event_id":row.get("event_id"),"fs_id":row.get("fs_id"),"market":_label(sel),"score":score,"delta_pp":round(delta,2),"elapsed":int(elapsed),"start_odds":round(first[1],3),"last_odds":round(last[1],3),"start_line":first[2],"last_line":last[2],"line_move":round(lm,2),"suspends":susp,"reopens":reop,"reopen_delta_pp":round(rd,2),"fingerprint":f"{mk}:{round(last[1],3)}:{last[2]}:{susp}:{reop}","created_ts":last[0]}
   if best is None or (sig["score"],abs(sig["delta_pp"]),abs(sig["reopen_delta_pp"]),abs(sig["line_move"]))>(best["score"],abs(best["delta_pp"]),abs(best["reopen_delta_pp"]),abs(best["line_move"])):best=sig
  if best:out.append(best)
 return out[:80]
def collector():
 while True:
  st=time.monotonic();collect_once();time.sleep(max(2,INTERVAL-(time.monotonic()-st)))
def prematch_collector():
 while True:
  st=time.monotonic();collect_prematch_once();time.sleep(max(30,PREMATCH_INTERVAL-(time.monotonic()-st)))
def flashscore_collector():
 while True:
  st=time.monotonic();refresh_flashscore();time.sleep(max(10,FS_INTERVAL-(time.monotonic()-st)))
def _authorized(h):return (not SECRET) or h.headers.get("Authorization","")=="Bearer "+SECRET
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):return
 def _send(self,code,obj):
  raw=json.dumps(obj,separators=(",",":"),ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.path.startswith("/health"):
   with LOCK:
    mc=sum(len(r.get("markets") or {}) for r in STATE.values());fx=len(FIXTURES);fsn=len(FS_MATCHES);fsl=sum(1 for f in FS_MATCHES.values() if str(f.get("status"))=="2")
   self._send(200,{"ok":True,"cycles":CYCLES,"last_cycle":LAST_CYCLE,"last_error":LAST_ERROR,"events":len(STATE),"markets":mc,"fixtures_today":fx,"flashscore_today":fsn,"flashscore_live":fsl,"last_flashscore":LAST_FS,"flashscore_error":FS_ERROR,"last_prematch":LAST_PREMATCH,"prematch_error":PREMATCH_ERROR,"flashscore_gate":True,"flashscore_live_gate":True,"selected_markets_only":True,"strongest_market_snapshot":True});return
  if not _authorized(self):self._send(401,{"ok":False,"error":"unauthorized"});return
  if self.path.startswith("/fixtures/live"):
   with LOCK:data=[dict(f) for f in FS_MATCHES.values() if str(f.get("status"))=="2"]
   self._send(200,{"ok":True,"source":"flashscore","fixtures":data,"count":len(data),"scope":"live"});return
  if self.path.startswith("/fixtures/today"):
   with LOCK:data=list(FIXTURES.values())
   self._send(200,{"ok":True,"source":"flashscore","fixtures":data,"count":len(data),"scope":"today"});return
  if self.path.startswith("/anomalies"):
   with LOCK:data=_anomalies()
   self._send(200,{"ok":True,"anomalies":data,"count":len(data),"flashscore_gate":True,"live_only":True});return
  if self.path.startswith("/snapshot"):
   with LOCK:data=_compact_events()
   self._send(200,{"ok":True,"events":data,"count":len(data),"flashscore_gate":True,"live_only":True,"strongest_market_snapshot":True});return
  self._send(404,{"ok":False,"error":"not found"})
def main():
 refresh_flashscore();collect_prematch_once();threading.Thread(target=collector,daemon=True).start();threading.Thread(target=prematch_collector,daemon=True).start();threading.Thread(target=flashscore_collector,daemon=True).start();log.info("MARKET_NODE_HTTP port=%d compact_api=1 flashscore_today=1 flashscore_live_gate=1 selected_markets=1 strongest_market_snapshot=1",PORT);ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()
if __name__=="__main__":main()
