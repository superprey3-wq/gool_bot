"""GOOL Market Server: precise LIVE TOTAL OVER/UNDER proguz ranking by period.

For every exact event/scope/line/bookmaker we evaluate the OVER/UNDER pair together.
OVER is supported when OVER shortens OR the paired UNDER drifts; UNDER is supported
when UNDER shortens OR the paired OVER drifts. This removes the previous bias caused
by evaluating each side in isolation.
"""
from __future__ import annotations
import json,os,statistics,time,sqlite3,threading,re
from collections import defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"));DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"));BEST_STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"))
HOST="0.0.0.0";PORT=int(os.getenv("GOOL_STRONG_FEED_PORT",os.getenv("SERVER_PORT","5056")));MIN_SCORE=float(os.getenv("GOOL_STRONG_MIN_SCORE","80"));MIN_MOVE=float(os.getenv("GOOL_STRONG_MIN_MOVE","3.0"));FAST_MIN_MOVE=float(os.getenv("GOOL_STRONG_FAST_MIN_MOVE","2.0"));MAX_AGE=int(os.getenv("GOOL_MARKET_FEED_MAX_AGE","300"));BETB2B_POLL=max(45,int(os.getenv("GOOL_BETB2B_POLL_SECONDS","45")))
try:import betb2b_market_signal as betb2b;BETB2B_AVAILABLE=True
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
  return [json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))],{"age":round(time.time()-row[1],1),"records":row[2],"id":row[0]}
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
def _scope(r):
 s=str(r.get("scope") or r.get("bettingScope") or "FULL_TIME").upper().replace("-","_").replace(" ","_")
 if s in {"FULL_TIME","FULLTIME","MATCH","REGULAR_TIME","FT"}:return "FULL_TIME"
 if s in {"FIRST_HALF","1ST_HALF","1H"}:return "FIRST_HALF"
 if s in {"SECOND_HALF","2ND_HALF","2H"}:return "SECOND_HALF"
 return s
def _minute(r):
 raw=str(r.get("minute") or r.get("match_minute") or r.get("status") or "");m=re.search(r"(\d{1,3})",raw)
 try:return int(m.group(1)) if m else None
 except Exception:return None
def _scope_live_ok(scope,r):
 if scope=="FULL_TIME":return True
 st=str(r.get("status") or r.get("match_status") or "").upper();minute=_minute(r)
 if scope=="FIRST_HALF":return not ("2H" in st or (minute is not None and minute>45))
 if scope=="SECOND_HALF":return not ("1H" in st or (minute is not None and minute<46))
 return False
def _score_pair(r):
 raw=str(r.get("score_live") or r.get("score") or "").strip();m=re.search(r"(\d+)\s*[:\-]\s*(\d+)",raw)
 if not m:return None
 try:return int(m.group(1)),int(m.group(2))
 except Exception:return None
def _source_name(r):
 b=str(r.get("bookmaker") or r.get("bookmaker_id") or "").strip();s=str(r.get("source") or "").upper()
 if "BETB2B" in s or "1XBET" in s or "1XBET" in b.upper():return "1xBet"
 if "KAMBI" in s or "KAMBI" in b.upper():return "Kambi/BetRivers"
 return b or s or "unknown"
def _book_id(r):return (_source_name(r),str(r.get("bookmaker_id") or r.get("bookmaker") or ""))
def _betb2b_confirmation(home,away,side,scope):
 if scope!="FULL_TIME" or not BETB2B_AVAILABLE:return {"available":False,"confirmed":False}
 try:
  sig=betb2b.signal_for_match(home,away);direction=int(getattr(sig,"direction",0) or 0);confirmed=(side=="OVER" and direction>0) or (side=="UNDER" and direction<0)
  return {"available":True,"confirmed":confirmed,"dot":getattr(sig,"dot","🟡"),"delta_pp":float(getattr(sig,"delta_pp",0.0) or 0.0),"fast":bool(getattr(sig,"fast",False)),"direction":direction}
 except Exception as exc:return {"available":False,"confirmed":False,"error":f"{type(exc).__name__}:{exc}"}
def _price_pct(r):
 try:return float((r.get("flow") or {}).get("delta_pct"))
 except Exception:return None
def _pair_support(book_rows,side):
 """Positive = movement into requested side, in decimal-price percentage magnitude."""
 own=next((r for r in book_rows if _ou_side(r)==side),None);opp_side="UNDER" if side=="OVER" else "OVER";opp=next((r for r in book_rows if _ou_side(r)==opp_side),None);vals=[];persistent=False;reversal=False
 if own:
  p=_price_pct(own);f=own.get("flow") or {};reversal|=bool(f.get("reversal"));persistent|=bool(f.get("persistence"))
  if p is not None:vals.append(-p)  # own shortening supports own side
 if opp:
  p=_price_pct(opp);f=opp.get("flow") or {};reversal|=bool(f.get("reversal"));persistent|=bool(f.get("persistence"))
  if p is not None:vals.append(p)   # opposite drifting supports own side
 vals=[v for v in vals if v>0]
 return (statistics.median(vals) if vals else None),persistent,reversal,own

def _candidate(base_key,market_rows,side):
 eid,scope,line_txt=base_key
 try:line=float(line_txt)
 except Exception:return None
 by_book=defaultdict(list)
 for r in market_rows:
  if _scope_live_ok(scope,r):by_book[_book_id(r)].append(r)
 supports=[];persistent_books=0;own_rows=[]
 for bid,rows in by_book.items():
  support,persist,reversal,own=_pair_support(rows,side)
  if support is None or support<0.6 or reversal or own is None:continue
  supports.append((bid,support,own));persistent_books+=int(persist);own_rows.append(own)
 if not supports:return None
 anchor=next((r for r in own_rows if _score_pair(r) is not None),own_rows[0]);pair=_score_pair(anchor);minute=_minute(anchor);med=statistics.median([x[1] for x in supports]);best=max(x[1] for x in supports);b2b=_betb2b_confirmation(anchor.get("home") or "",anchor.get("away") or "",side,scope)
 sources={x[0][0] for x in supports};confirmations=len(sources)+(1 if b2b.get("confirmed") and "1xBet" not in sources else 0)
 if confirmations<2:return None
 fast_exception=(scope=="FULL_TIME" and med>=FAST_MIN_MOVE and b2b.get("confirmed") and b2b.get("fast") and persistent_books>=1)
 if med<MIN_MOVE and not fast_exception:return None
 if scope=="FULL_TIME":
  if pair is None:return None
  goals=sum(pair)
  if side=="UNDER" and goals>=line:return None
  if side=="OVER" and goals>line:return None
 elif scope=="FIRST_HALF" and pair is not None and side=="UNDER" and sum(pair)>=line:return None
 score=58+min(16,confirmations*5)+min(14,med*3.0)+min(8,persistent_books*2)+(5 if b2b.get("confirmed") else 0)+(2 if fast_exception else 0);score=round(min(100,score),1)
 if score<MIN_SCORE:return None
 priced=[]
 for r in own_rows:
  try:o=float(r.get("odd"))
  except Exception:continue
  if 1.30<=o<=3.20:priced.append((o,r))
 if not priced:return None
 odd,price_row=max(priced,key=lambda z:z[0]);key=(eid,"TOTAL",scope,line_txt,side)
 result={"id":"|".join(key),"event_id":eid,"home":anchor.get("home") or "","away":anchor.get("away") or "","score_live":f"{pair[0]}:{pair[1]}" if pair else "","status":anchor.get("status") or "","minute":minute,"market":"TOTAL","scope":scope,"line":line,"side":side,"odd":odd,"odd_source":_source_name(price_row),"books":confirmations,"moving_sources":sorted(sources),"move_pp":round(med,3),"median_delta_pct":round(-med,3),"best_move_pp":round(best,3),"persistent_books":persistent_books,"strength":score,"fast_exception":bool(fast_exception),"betb2b":b2b,"ts":time.time()}
 print(f"PROGRUZ_CANDIDATE event={eid} scope={scope} score={result['score_live']} minute={minute} pick={side} {line:g} odd={odd:.2f} confirms={confirmations} paired_move={med:.2f}% strength={score:.0f}",flush=True);return result
def strong_rows():
 records,source,meta=_records();markets=defaultdict(list);total_live=0;side_rows={"OVER":0,"UNDER":0}
 for r in records:
  if not isinstance(r,dict) or not _is_total(r) or not _is_live(r):continue
  side=_ou_side(r);scope=_scope(r)
  if not side or scope not in {"FULL_TIME","FIRST_HALF","SECOND_HALF"} or not _scope_live_ok(scope,r):continue
  line=str(r.get("line") if r.get("line") is not None else "")
  if not r.get("event_id") or not line:continue
  total_live+=1;side_rows[side]+=1;markets[(str(r.get("event_id")),scope,line)].append(r)
 candidates=[]
 for k,rows in markets.items():
  for side in ("OVER","UNDER"):
   c=_candidate(k,rows,side)
   if c:candidates.append(c)
 best={}
 for c in candidates:
  bucket=(c["event_id"],c["scope"]);rank=(c["strength"],c["books"],c["persistent_books"],c["move_pp"],c["odd"])
  if bucket not in best or rank>best[bucket][0]:best[bucket]=(rank,c)
 out=[x[1] for x in best.values()];out.sort(key=lambda x:(x["strength"],x["books"],x["persistent_books"],x["move_pp"]),reverse=True)
 print(f"PROGRUZ_SIDES rows_over={side_rows['OVER']} rows_under={side_rows['UNDER']} candidates_over={sum(x['side']=='OVER' for x in candidates)} candidates_under={sum(x['side']=='UNDER' for x in candidates)}",flush=True);return out[:20],source,meta,len(records),total_live,side_rows
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
   strong,source,meta,n,total_live,side_rows=strong_rows();common={"ok":True,"ts":time.time(),"mode":"LIVE_TOTAL_OU_PAIRED_V4","market_source":source,"market_records":n,"live_total_rows":total_live,"side_rows":side_rows,"min_move_pct":MIN_MOVE,"periods":["FULL_TIME","FIRST_HALF","SECOND_HALF"],"sides":["OVER","UNDER"],"betb2b_1xbet":BETB2B_AVAILABLE,"snapshot":meta}
   body={**common,"strong":strong,"best_bet":best_bet_payload().get("signal")} if path not in ("/health","/markets") else ({**common,"db":str(DB),"best_bet_state_exists":BEST_STATE.exists()} if path=="/health" else common)
  raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,fmt,*args):return
if __name__=="__main__":
 threading.Thread(target=_betb2b_loop,name="betb2b-confirm",daemon=True).start();print(f"GOOL_MARKET_SERVER TOTAL O/U PAIRED V4 port={PORT} strong>={MIN_SCORE} min_move={MIN_MOVE}% over_under=paired_symmetric",flush=True);ThreadingHTTPServer((HOST,PORT),H).serve_forever()
