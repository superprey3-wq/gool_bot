"""GOOL Market Server: precise LIVE TOTAL O/U PROGRUZ ranking."""
from __future__ import annotations
import json,os,statistics,time,sqlite3,threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"));DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"));BEST_STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"));HOST="0.0.0.0";PORT=int(os.getenv("GOOL_STRONG_FEED_PORT",os.getenv("SERVER_PORT","5056")));MIN_SCORE=float(os.getenv("GOOL_STRONG_MIN_SCORE","80"));MAX_AGE=int(os.getenv("GOOL_MARKET_FEED_MAX_AGE","300"));BETB2B_POLL=max(45,int(os.getenv("GOOL_BETB2B_POLL_SECONDS","45")))
try:
 import betb2b_market_signal as betb2b;BETB2B_AVAILABLE=True
except Exception as exc:betb2b=None;BETB2B_AVAILABLE=False;BETB2B_IMPORT_ERROR=f"{type(exc).__name__}:{exc}"
def _load(path):
 try:d=json.loads(path.read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _db_records():
 if not DB.exists():return [],None
 c=None
 try:
  c=sqlite3.connect(DB,timeout=5);row=c.execute("SELECT id,ts,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
  if not row or time.time()-float(row[1])>MAX_AGE:return [],None
  rows=[json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))];return rows,{"age":round(time.time()-row[1],1),"records":row[2],"id":row[0]}
 except Exception:return [],None
 finally:
  if c:
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
def _is_total(r):
 m=str(r.get("market") or r.get("betting_type") or "").upper().replace("-","_").replace(" ","_");return m in {"TOTAL","OVER_UNDER","OU","O/U"} or "OVER_UNDER" in m or m.endswith("TOTAL")
def _ou_side(r):
 s=str(r.get("side") or r.get("selection") or r.get("name") or "").upper().strip()
 if s in {"OVER","O","ТБ","TB"} or s.startswith("OVER "):return "OVER"
 if s in {"UNDER","U","ТМ","TM"} or s.startswith("UNDER "):return "UNDER"
 return ""
def _is_live(r):
 st=str(r.get("status") or r.get("match_status") or "").upper().strip()
 if st in {"FT","FINISHED","ENDED","NOT_STARTED","SCHEDULED","NS"}:return False
 if st in {"LIVE","1H","2H","HT","HALFTIME","BREAK","IN_PLAY","INPLAY"}:return True
 return bool(r.get("score") or r.get("minute") or r.get("live"))
def _betb2b_confirmation(home,away,side):
 if not BETB2B_AVAILABLE:return {"available":False,"confirmed":False}
 try:
  sig=betb2b.signal_for_match(home,away);direction=int(getattr(sig,"direction",0) or 0);confirmed=(side=="OVER" and direction>0) or (side=="UNDER" and direction<0)
  return {"available":True,"confirmed":confirmed,"dot":getattr(sig,"dot","🟡"),"delta_pp":float(getattr(sig,"delta_pp",0.0) or 0.0),"fast":bool(getattr(sig,"fast",False)),"direction":direction}
 except Exception as exc:return {"available":False,"confirmed":False,"error":f"{type(exc).__name__}:{exc}"}
def _source_name(r):
 s=str(r.get("source") or "").upper();b=str(r.get("bookmaker") or r.get("bookmaker_id") or "")
 if "BETB2B" in s or "1XBET" in s or "1XBET" in b.upper():return "1xBet"
 if "KAMBI" in s or "KAMBI" in b.upper():return "Kambi"
 if "OLE2" in s or "LSAPP" in s or "LSAPP" in b.upper():return "LSApp"
 return b or s or "unknown"
def _candidate(key,rows):
 moving=[]
 for x in rows:
  f=x.get("flow") or {}
  try:p=float(f.get("delta_pct"))
  except Exception:continue
  if p<-.6 and not bool(f.get("reversal")):moving.append((x,p))
 if not moving:return None
 sources={_source_name(x) for x,_ in moving};pcts=[p for _,p in moving];persist=sum(int(bool((x.get("flow") or {}).get("persistence"))) for x,_ in moving);r=min(moving,key=lambda z:z[1])[0];b2b=_betb2b_confirmation(r.get("home") or "",r.get("away") or "",key[4]);med=statistics.median(pcts);best=min(pcts)
 # A strong pick needs two independently moving sources. BetB2B direction can be the second confirmation.
 confirmations=len(sources)+(1 if b2b.get("confirmed") and "1xBet" not in sources else 0)
 if confirmations<2:return None
 # Prefer sustained consensus over a single violent tick. 80 means strong, 90+ exceptional.
 score=58+min(16,confirmations*5)+min(14,abs(med)*3.0)+min(8,persist*2)+(5 if b2b.get("confirmed") else 0)
 score=round(min(100,score),1)
 if score<MIN_SCORE:return None
 try:odd=float(r.get("odd"))
 except Exception:odd=None
 if odd is None or odd<1.30 or odd>3.20:return None
 return {"id":"|".join(key),"event_id":key[0],"home":r.get("home") or "","away":r.get("away") or "","score_live":r.get("score") or "","status":r.get("status") or "","market":"TOTAL","scope":key[2],"line":r.get("line"),"side":key[4],"odd":odd,"books":confirmations,"moving_sources":sorted(sources),"median_delta_pct":round(med,3),"best_delta_pct":round(best,3),"persistent_books":persist,"strength":score,"betb2b":b2b,"ts":time.time()}
def strong_rows():
 records,source,meta=_records();groups=defaultdict(list);total_live=0
 for r in records:
  if not isinstance(r,dict) or not _is_total(r) or not _is_live(r):continue
  side=_ou_side(r)
  if not side:continue
  total_live+=1;key=(str(r.get("event_id") or ""),"TOTAL",str(r.get("scope") or "FULL_TIME"),str(r.get("line") if r.get("line") is not None else ""),side)
  if key[0] and key[3]:groups[key].append(r)
 candidates=[c for k,v in groups.items() if (c:=_candidate(k,v))]
 # One precise TOTAL pick per match. Competing OVER/UNDER/lines never spam Telegram.
 best={}
 for c in candidates:
  eid=c["event_id"];rank=(c["strength"],c["books"],c["persistent_books"],abs(c["median_delta_pct"]),c["odd"])
  if eid not in best or rank>best[eid][0]:best[eid]=(rank,c)
 out=[x[1] for x in best.values()];out.sort(key=lambda x:(x["strength"],x["books"],x["persistent_books"],abs(x["median_delta_pct"])),reverse=True);return out[:20],source,meta,len(records),total_live
def _betb2b_loop():
 if not BETB2B_AVAILABLE:print(f"BETB2B_CONFIRM disabled import={globals().get('BETB2B_IMPORT_ERROR','unknown')}",flush=True);return
 print("BETB2B_CONFIRM old 1xBet live TOTAL sampler enabled",flush=True)
 while True:
  try:betb2b.sample_live(force=True)
  except Exception as exc:print(f"BETB2B_CONFIRM sample failed {type(exc).__name__}:{exc}",flush=True)
  time.sleep(BETB2B_POLL)
def best_bet_payload():
 d=_load(BEST_STATE);sig=d.get("signal") if isinstance(d,dict) else None;return {"ok":True,"ts":time.time(),"worker_ts":d.get("ts") if isinstance(d,dict) else None,"live":d.get("live",0) if isinstance(d,dict) else 0,"sent":d.get("sent",0) if isinstance(d,dict) else 0,"signal":sig if isinstance(sig,dict) else None}
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  path=self.path.split("?",1)[0]
  if path not in ("/","/strong","/bestbet","/health","/markets"):self.send_response(404);self.end_headers();return
  if path=="/bestbet":body=best_bet_payload()
  else:
   strong,source,meta,n,total_live=strong_rows();common={"ok":True,"ts":time.time(),"mode":"LIVE_TOTAL_OU_PRECISE","market_source":source,"market_records":n,"live_total_rows":total_live,"betb2b_1xbet":BETB2B_AVAILABLE,"snapshot":meta}
   body={**common,"strong":strong,"best_bet":best_bet_payload().get("signal")} if path not in ("/health","/markets") else ({**common,"db":str(DB),"best_bet_state_exists":BEST_STATE.exists()} if path=="/health" else common)
  raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,fmt,*args):return
if __name__=="__main__":
 threading.Thread(target=_betb2b_loop,name="betb2b-confirm",daemon=True).start();print(f"GOOL_MARKET_SERVER PRECISE TOTAL O/U port={PORT} strong>={MIN_SCORE} one_pick_per_match=on",flush=True);ThreadingHTTPServer((HOST,PORT),H).serve_forever()
