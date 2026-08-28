"""Read-only strong market-flow feed for the main GOOL bot."""
from __future__ import annotations
import json, os, statistics, time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"))
HOST="0.0.0.0"; PORT=int(os.getenv("GOOL_STRONG_FEED_PORT",os.getenv("SERVER_PORT","5056")))
MIN_SCORE=float(os.getenv("GOOL_STRONG_MIN_SCORE","80"))

def _load():
 try:
  d=json.loads(STATE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {}
 except Exception:return {}

def _records(d):
 for k in ("records","market_records","odds","normalized_odds"):
  v=d.get(k)
  if isinstance(v,list): return v
 return []

def strong_rows():
 d=_load(); groups=defaultdict(list)
 for r in _records(d):
  if not isinstance(r,dict):continue
  f=r.get("flow") or {}; pct=f.get("delta_pct")
  try:pct=float(pct)
  except Exception:continue
  if pct>=-0.6 or bool(f.get("reversal")):continue
  key=(str(r.get("event_id") or ""),str(r.get("market") or ""),str(r.get("scope") or ""),str(r.get("line") if r.get("line") is not None else ""),str(r.get("side") or ""))
  if key[0] and key[1] and key[4]:groups[key].append(r)
 out=[]
 for key,rows in groups.items():
  books={str(x.get("bookmaker") or x.get("bookmaker_id") or "") for x in rows if x.get("bookmaker") or x.get("bookmaker_id")}
  pcts=[]; persist=0
  for x in rows:
   try:pcts.append(float((x.get("flow") or {}).get("delta_pct")))
   except Exception:pass
   persist+=int(bool((x.get("flow") or {}).get("persistence")))
  if len(books)<2 or not pcts:continue
  med=statistics.median(pcts); best=min(pcts)
  score=55 + min(18,len(books)*4) + min(15,abs(med)*4) + min(10,persist*3)
  score=round(min(100,score),1)
  if score<MIN_SCORE:continue
  r=rows[0]; out.append({"id":"|".join(key),"event_id":key[0],"home":r.get("home") or "","away":r.get("away") or "","score_live":r.get("score") or "","status":r.get("status") or "","market":key[1],"scope":key[2],"line":r.get("line"),"side":key[4],"odd":r.get("odd"),"books":len(books),"median_delta_pct":round(med,3),"best_delta_pct":round(best,3),"persistent_books":persist,"strength":score,"ts":time.time()})
 out.sort(key=lambda x:(x["strength"],x["books"],abs(x["median_delta_pct"])),reverse=True)
 return out[:20]

class H(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path.split("?",1)[0] not in ("/","/strong","/health"):
   self.send_response(404);self.end_headers();return
  body={"ok":True,"ts":time.time(),"strong":strong_rows()} if not self.path.startswith("/health") else {"ok":True,"ts":time.time(),"state_exists":STATE.exists()}
  raw=json.dumps(body,ensure_ascii=False).encode()
  self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,fmt,*args):return

if __name__=="__main__":
 print(f"GOOL_STRONG_FEED starting port={PORT} min_strength={MIN_SCORE}",flush=True)
 ThreadingHTTPServer((HOST,PORT),H).serve_forever()
