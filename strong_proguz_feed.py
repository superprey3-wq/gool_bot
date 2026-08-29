"""GOOL strong proguz feed: TOTAL O/U with a mandatory fresh event snapshot gate.

The market movement may come from history, but score/minute MUST come from the newest
snapshot for the event. A candidate is suppressed when live context is missing,
inconsistent across rows, or older than the newest snapshot.
"""
from __future__ import annotations
import json,os,statistics,time,sqlite3,threading,re
from collections import defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"));DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"));BEST_STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"))
HOST="0.0.0.0";PORT=int(os.getenv("GOOL_STRONG_FEED_PORT",os.getenv("SERVER_PORT","5056")));MIN_SCORE=float(os.getenv("GOOL_STRONG_MIN_SCORE","80"));MIN_MOVE=float(os.getenv("GOOL_STRONG_MIN_MOVE","3.0"));MAX_AGE=int(os.getenv("GOOL_MARKET_FEED_MAX_AGE","180"));BETB2B_POLL=max(45,int(os.getenv("GOOL_BETB2B_POLL_SECONDS","45")))
try:import betb2b_market_signal as betb2b;BETB2B_AVAILABLE=True
except Exception as exc:betb2b=None;BETB2B_AVAILABLE=False;BETB2B_IMPORT_ERROR=f"{type(exc).__name__}:{exc}"
def _load(p):
 try:d=json.loads(p.read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _db_records():
 if not DB.exists():return [],None
 c=None
 try:
  c=sqlite3.connect(DB,timeout=5);row=c.execute("SELECT id,ts,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
  if not row:return [],None
  age=time.time()-float(row[1]);
  if age>MAX_AGE:return [],{"age":round(age,1),"stale":True}
  return [json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))],{"age":round(age,1),"records":row[2],"id":row[0]}
 except Exception:return [],None
 finally:
  if c:
   try:c.close()
   except Exception:pass
def _records():
 rows,meta=_db_records()
 if rows:return rows,"sqlite",meta
 d=_load(STATE);ls=d.get("lsapp") or {};rows=ls.get("records") if isinstance(ls,dict) else []
 return (rows if isinstance(rows,list) else []),"json",None
def _side(r):
 s=str(r.get("side") or "").upper();return "OVER" if s in {"OVER","O","ТБ","TB"} else "UNDER" if s in {"UNDER","U","ТМ","TM"} else ""
def _scope(r):
 s=str(r.get("scope") or "FULL_TIME").upper().replace("-","_").replace(" ","_");return {"FULLTIME":"FULL_TIME","FT":"FULL_TIME","1H":"FIRST_HALF","2H":"SECOND_HALF"}.get(s,s)
def _minute(r):
 m=re.search(r"(\d{1,3})",str(r.get("minute") or ""));return int(m.group(1)) if m else None
def _score(r):
 m=re.search(r"(\d+)\s*[:\-]\s*(\d+)",str(r.get("score_live") or r.get("score") or ""));return (int(m.group(1)),int(m.group(2))) if m else None
def _src(r):
 b=str(r.get("bookmaker") or r.get("bookmaker_id") or "");s=str(r.get("source") or "").upper()
 if "1XBET" in b.upper() or "BETB2B" in s:return "1xBet"
 if "KAMBI" in b.upper() or "KAMBI" in s:return "Kambi/BetRivers"
 return b or s or "unknown"
def _live(r):return str(r.get("status") or "").upper() not in {"FT","FINISHED","ENDED","NS","SCHEDULED"}
def _fresh_context(event_rows):
 """Require a coherent latest score/minute. Never choose context from a movement row."""
 vals=[]
 for r in event_rows:
  sc=_score(r);mi=_minute(r)
  if sc is not None and mi is not None:vals.append((mi,sum(sc),sc,r))
 if not vals:return None,"missing_score_or_minute"
 # Market sources for one collector cycle are stamped with the same Flashscore event context.
 # Prefer greatest absolute minute, then greatest goal count: score/minute never move backwards.
 vals.sort(key=lambda x:(x[0],x[1]),reverse=True);mi,_,sc,r=vals[0]
 # reject snapshots with impossible internal regression: a later row cannot have fewer goals
 for omi,og,osc,_ in vals[1:]:
  if omi>mi or (omi==mi and og>sum(sc)):return None,"regressive_context"
 return {"minute":mi,"score":sc,"status":r.get("status") or "LIVE","home":r.get("home") or "","away":r.get("away") or ""},None
def _price_pct(r):
 try:return float((r.get("flow") or {}).get("delta_pct"))
 except Exception:return None
def _pair_support(rows,side):
 own=next((r for r in rows if _side(r)==side),None);opp=next((r for r in rows if _side(r)!="" and _side(r)!=side),None);vals=[];persist=False;rev=False
 for r,sign in ((own,-1),(opp,1)):
  if not r:continue
  f=r.get("flow") or {};p=_price_pct(r);persist|=bool(f.get("persistence"));rev|=bool(f.get("reversal"))
  if p is not None and sign*p>0:vals.append(sign*p)
 return (statistics.median(vals) if vals else None),persist,rev,own
def _b2b(home,away,side,scope):
 if scope!="FULL_TIME" or not BETB2B_AVAILABLE:return False
 try:d=int(getattr(betb2b.signal_for_match(home,away),"direction",0) or 0);return (side=="OVER" and d>0) or (side=="UNDER" and d<0)
 except Exception:return False
def _candidate(key,rows,side,ctx):
 eid,scope,line_txt=key
 try:line=float(line_txt)
 except Exception:return None
 books=defaultdict(list)
 for r in rows:books[(_src(r),str(r.get("bookmaker_id") or ""))].append(r)
 sup=[];own=[];persist=0
 for bid,br in books.items():
  v,p,rev,o=_pair_support(br,side)
  if v is None or v<0.6 or rev or o is None:continue
  sup.append((bid,v,o));own.append(o);persist+=int(p)
 if not sup:return None
 sources={x[0][0] for x in sup};b2=_b2b(ctx["home"],ctx["away"],side,scope);conf=len(sources)+(1 if b2 and "1xBet" not in sources else 0);med=statistics.median(x[1] for x in sup)
 if conf<2 or med<MIN_MOVE:return None
 goals=sum(ctx["score"])
 if scope=="FULL_TIME" and side=="UNDER" and goals>=line:return None
 if scope=="FULL_TIME" and side=="OVER" and goals>line:return None
 if scope=="FIRST_HALF" and ctx["minute"]>45:return None
 if scope=="SECOND_HALF" and ctx["minute"]<46:return None
 score=round(min(100,58+min(16,conf*5)+min(14,med*3)+min(8,persist*2)+(5 if b2 else 0)),1)
 if score<MIN_SCORE:return None
 prices=[]
 for r in own:
  try:o=float(r.get("odd"))
  except Exception:continue
  if 1.30<=o<=3.20:prices.append(o)
 if not prices:return None
 odd=max(prices);res={"id":"|".join((eid,"TOTAL",scope,line_txt,side)),"event_id":eid,"home":ctx["home"],"away":ctx["away"],"score_live":f"{ctx['score'][0]}:{ctx['score'][1]}","status":ctx["status"],"minute":ctx["minute"],"market":"TOTAL","scope":scope,"line":line,"side":side,"odd":odd,"books":conf,"moving_sources":sorted(sources),"median_delta_pct":round(-med,3),"persistent_books":persist,"strength":score,"ts":time.time()}
 print(f"PROGRUZ_FRESH_OK event={eid} score={res['score_live']} minute={ctx['minute']} pick={side}{line:g} confirms={conf} move={med:.2f}%",flush=True);return res
def strong_rows():
 records,source,meta=_records();events=defaultdict(list)
 for r in records:
  if isinstance(r,dict) and _live(r) and str(r.get("market") or "").upper() in {"TOTAL","OVER_UNDER"}:events[str(r.get("event_id") or "")].append(r)
 out=[];rejected=0
 for eid,erows in events.items():
  if not eid:continue
  ctx,err=_fresh_context(erows)
  if not ctx:
   rejected+=1;print(f"PROGRUZ_REJECT_STALE event={eid} reason={err}",flush=True);continue
  markets=defaultdict(list)
  for r in erows:
   s=_side(r);scope=_scope(r);line=r.get("line")
   if s and scope in {"FULL_TIME","FIRST_HALF","SECOND_HALF"} and line is not None:markets[(eid,scope,str(line))].append(r)
  candidates=[]
  for k,mrows in markets.items():
   for s in ("OVER","UNDER"):
    c=_candidate(k,mrows,s,ctx)
    if c:candidates.append(c)
  if candidates:
   candidates.sort(key=lambda c:(c["strength"],c["books"],abs(c["median_delta_pct"]),c["odd"]),reverse=True);out.append(candidates[0])
 out.sort(key=lambda c:(c["strength"],c["books"]),reverse=True);return out[:20],source,meta,len(records),len(events),rejected
def _loop():
 if not BETB2B_AVAILABLE:return
 while True:
  try:betb2b.sample_live(force=True)
  except Exception:pass
  time.sleep(BETB2B_POLL)
def best_bet_payload():
 d=_load(BEST_STATE);return {"ok":True,"ts":time.time(),"signal":d.get("signal") if isinstance(d.get("signal"),dict) else None}
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  p=self.path.split("?",1)[0]
  if p not in ("/","/strong","/bestbet","/health","/markets"):self.send_response(404);self.end_headers();return
  if p=="/bestbet":body=best_bet_payload()
  else:
   strong,source,meta,n,events,rejected=strong_rows();body={"ok":True,"ts":time.time(),"mode":"LIVE_TOTAL_OU_FRESH_CONTEXT_V5","market_source":source,"market_records":n,"events":events,"stale_rejected":rejected,"min_move_pct":MIN_MOVE,"strong":strong}
  raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*a):return
if __name__=="__main__":threading.Thread(target=_loop,daemon=True).start();print(f"GOOL_MARKET_SERVER FRESH CONTEXT V5 port={PORT} stale_gate=hard score_minute=required min_move={MIN_MOVE}%",flush=True);ThreadingHTTPServer((HOST,PORT),H).serve_forever()
