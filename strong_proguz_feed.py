"""GOOL Market Server HTTP feed: persistent PROGRUZ + remote BEST BET."""
from __future__ import annotations
import json,os,statistics,time,sqlite3
from collections import defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"));DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"));BEST_STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"))
HOST="0.0.0.0";PORT=int(os.getenv("GOOL_STRONG_FEED_PORT",os.getenv("SERVER_PORT","5056")));MIN_SCORE=float(os.getenv("GOOL_STRONG_MIN_SCORE","80"));MAX_AGE=int(os.getenv("GOOL_MARKET_FEED_MAX_AGE","300"))
def _load(path):
 try:d=json.loads(path.read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _db_records():
 if not DB.exists():return [],None
 try:
  c=sqlite3.connect(DB,timeout=5);row=c.execute("SELECT id,ts,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
  if not row or time.time()-float(row[1])>MAX_AGE:return [],None
  rows=[json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))];return rows,{"age":round(time.time()-row[1],1),"records":row[2],"id":row[0]}
 except Exception:return [],None
 finally:
  try:c.close()
  except Exception:pass
def _records():
 rows,meta=_db_records()
 if rows:return rows,"sqlite",meta
 d=_load(STATE);ls=d.get("lsapp") or {};rows=ls.get("records") if isinstance(ls,dict) else None
 if not isinstance(rows,list):
  rows=[]
  for k in ("records","market_records","odds","normalized_odds"):
   if isinstance(d.get(k),list):rows=d[k];break
 return rows,"json" if rows else "none",None
def strong_rows():
 records,source,meta=_records();groups=defaultdict(list)
 for r in records:
  if not isinstance(r,dict):continue
  f=r.get("flow") or {};pct=f.get("delta_pct")
  try:pct=float(pct)
  except Exception:continue
  if pct>=-.6 or bool(f.get("reversal")):continue
  key=(str(r.get("event_id") or ""),str(r.get("market") or ""),str(r.get("scope") or ""),str(r.get("line") if r.get("line") is not None else ""),str(r.get("side") or ""))
  if key[0] and key[1] and key[4]:groups[key].append(r)
 out=[]
 for key,rows in groups.items():
  books={str(x.get("bookmaker") or x.get("bookmaker_id") or "") for x in rows if x.get("bookmaker") or x.get("bookmaker_id")};pcts=[];persist=0
  for x in rows:
   try:pcts.append(float((x.get("flow") or {}).get("delta_pct")))
   except Exception:pass
   persist+=int(bool((x.get("flow") or {}).get("persistence")))
  if len(books)<2 or not pcts:continue
  med=statistics.median(pcts);best=min(pcts);score=round(min(100,55+min(18,len(books)*4)+min(15,abs(med)*4)+min(10,persist*3)),1)
  if score<MIN_SCORE:continue
  r=rows[0];out.append({"id":"|".join(key),"event_id":key[0],"home":r.get("home") or "","away":r.get("away") or "","score_live":r.get("score") or "","status":r.get("status") or "","market":key[1],"scope":key[2],"line":r.get("line"),"side":key[4],"odd":r.get("odd"),"books":len(books),"median_delta_pct":round(med,3),"best_delta_pct":round(best,3),"persistent_books":persist,"strength":score,"source":source,"ts":time.time()})
 out.sort(key=lambda x:(x["strength"],x["books"],abs(x["median_delta_pct"])),reverse=True);return out[:20],source,meta,len(records)
def best_bet_payload():
 d=_load(BEST_STATE);sig=d.get("signal") if isinstance(d,dict) else None;return {"ok":True,"ts":time.time(),"worker_ts":d.get("ts") if isinstance(d,dict) else None,"live":d.get("live",0) if isinstance(d,dict) else 0,"sent":d.get("sent",0) if isinstance(d,dict) else 0,"signal":sig if isinstance(sig,dict) else None}
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  path=self.path.split("?",1)[0]
  if path not in ("/","/strong","/bestbet","/health","/markets"):
   self.send_response(404);self.end_headers();return
  if path=="/bestbet":body=best_bet_payload()
  else:
   strong,source,meta,n=strong_rows()
   if path=="/health":body={"ok":True,"ts":time.time(),"market_source":source,"market_records":n,"snapshot":meta,"db":str(DB),"best_bet_state_exists":BEST_STATE.exists()}
   elif path=="/markets":body={"ok":True,"ts":time.time(),"source":source,"records":n,"snapshot":meta}
   else:body={"ok":True,"ts":time.time(),"market_source":source,"market_records":n,"strong":strong,"best_bet":best_bet_payload().get("signal")}
  raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,fmt,*args):return
if __name__=="__main__":
 print(f"GOOL_MARKET_SERVER feed starting port={PORT} strong>={MIN_SCORE} sqlite={DB}",flush=True);ThreadingHTTPServer((HOST,PORT),H).serve_forever()
