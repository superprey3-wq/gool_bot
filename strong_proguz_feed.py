"""Monkey strong PROGRUZ: TOTAL O/U movement validated by unified Flashscore live truth.

Market movement starts the candidate. Fresh Flashscore score/minute is mandatory.
Rolling live pressure/momentum validates whether OVER/UNDER agrees with the actual
match state. Strong signals also require usable live-stat coverage and either
persistent movement or a materially larger multi-source move.
"""
from __future__ import annotations
import json,os,statistics,time,sqlite3
from collections import defaultdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
STATE=Path(os.getenv("GOOL_MARKET_STATE","/home/container/market_node_state.json"));DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"));BEST_STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"));LIVE_STATE=Path(os.getenv("GOOL_MONKEY_LIVE_CONTEXT","/home/container/monkey_live_context.json"))
HOST="0.0.0.0";PORT=int(os.getenv("GOOL_STRONG_FEED_PORT",os.getenv("SERVER_PORT","5056")));MIN_SCORE=float(os.getenv("GOOL_STRONG_MIN_SCORE","80"));MIN_MOVE=float(os.getenv("GOOL_STRONG_MIN_MOVE","3.0"));MAX_AGE=int(os.getenv("GOOL_MARKET_FEED_MAX_AGE","180"));LIVE_MAX_AGE=int(os.getenv("GOOL_MONKEY_LIVE_MAX_AGE","45"));MIN_STATS_KEYS=int(os.getenv("GOOL_STRONG_MIN_STATS_KEYS","3"));MIN_UNPERSISTED_MOVE=float(os.getenv("GOOL_STRONG_MIN_UNPERSISTED_MOVE","4.5"))
try:import betb2b_market_signal as betb2b;BETB2B_AVAILABLE=True
except Exception:betb2b=None;BETB2B_AVAILABLE=False

def _load(p):
 try:d=json.loads(p.read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _records():
 if DB.exists():
  c=None
  try:
   c=sqlite3.connect(DB,timeout=5);row=c.execute("SELECT id,ts,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
   if row and time.time()-float(row[1])<=MAX_AGE:return [json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))],"sqlite",{"age":round(time.time()-row[1],1),"records":row[2]}
  except Exception:pass
  finally:
   if c:
    try:c.close()
    except Exception:pass
 d=_load(STATE);ls=d.get("lsapp") or {};rows=ls.get("records") if isinstance(ls,dict) else [];return (rows if isinstance(rows,list) else []),"json",None
def _truth():
 d=_load(LIVE_STATE);ts=float(d.get("ts") or 0);age=time.time()-ts if ts else 9999;events=d.get("events") if isinstance(d.get("events"),dict) else {};return events,age
def _side(r):
 s=str(r.get("side") or "").upper();return "OVER" if s in {"OVER","O","ТБ","TB"} else "UNDER" if s in {"UNDER","U","ТМ","TM"} else ""
def _scope(r):
 s=str(r.get("scope") or "FULL_TIME").upper().replace("-","_").replace(" ","_");return {"FULLTIME":"FULL_TIME","FT":"FULL_TIME","1H":"FIRST_HALF","2H":"SECOND_HALF"}.get(s,s)
def _src(r):
 b=str(r.get("bookmaker") or r.get("bookmaker_id") or "");s=str(r.get("source") or "").upper()
 if "1XBET" in b.upper() or "BETB2B" in s:return "1xBet"
 if "KAMBI" in b.upper() or "KAMBI" in s:return "Kambi/BetRivers"
 return b or s or "unknown"
def _price_pct(r):
 try:return float((r.get("flow") or {}).get("delta_pct"))
 except Exception:return None
def _pair_support(rows,side):
 own=next((r for r in rows if _side(r)==side),None);opp=next((r for r in rows if _side(r) and _side(r)!=side),None);vals=[];persist=False;rev=False
 for r,sign in ((own,-1),(opp,1)):
  if not r:continue
  f=r.get("flow") or {};p=_price_pct(r);persist|=bool(f.get("persistence"));rev|=bool(f.get("reversal"))
  if p is not None and sign*p>0:vals.append(sign*p)
 return (statistics.median(vals) if vals else None),persist,rev,own
def _b2b(home,away,side,scope):
 if scope!="FULL_TIME" or not BETB2B_AVAILABLE:return False
 try:d=int(getattr(betb2b.signal_for_match(home,away),"direction",0) or 0);return (side=="OVER" and d>0) or (side=="UNDER" and d<0)
 except Exception:return False
def _sum_stat(stats,key):
 try:v=stats.get(key) or [0,0];return float(v[0] or 0)+float(v[1] or 0)
 except Exception:return 0.0
def _stats_coverage(stats):
 keys=("xg","shots","shots_on_target","big_chances","touches_box","corners")
 return sum(1 for k in keys if k in stats and isinstance(stats.get(k),(list,tuple)) and len(stats.get(k))>=2)
def _live_adjust(ctx,side):
 """Return (score adjustment, reject reason, diagnostic context)."""
 stats=ctx.get("stats") if isinstance(ctx.get("stats"),dict) else {};coverage=_stats_coverage(stats);p=ctx.get("pressure") if isinstance(ctx.get("pressure"),dict) else {}
 pressure=float(p.get("score") or 0);momentum=float(p.get("momentum") or 0);quality=float(p.get("quality") or 0);minute=int(ctx.get("minute") or 0)
 xg=_sum_stat(stats,"xg");shots=_sum_stat(stats,"shots");sot=_sum_stat(stats,"shots_on_target");big=_sum_stat(stats,"big_chances");touches=_sum_stat(stats,"touches_box");corners=_sum_stat(stats,"corners")
 pace=0.0
 if minute>0:pace=min(100.0,(xg/max(1,minute))*900+(sot/max(1,minute))*320+(big/max(1,minute))*500+(touches/max(1,minute))*28)
 hot=max(pressure,pace);diag={"coverage":coverage,"pressure":round(pressure,1),"momentum":round(momentum,1),"quality":round(quality,1),"pace":round(pace,1),"xg":round(xg,2),"shots":round(shots,1),"sot":round(sot,1),"big":round(big,1),"touches_box":round(touches,1),"corners":round(corners,1)}
 if coverage<MIN_STATS_KEYS:return 0,"insufficient_live_stats",diag
 if side=="UNDER":
  if momentum>=72 or hot>=82:return 0,"under_conflicts_hot_live",diag
  if minute>=70 and (momentum>=58 or hot>=70):return 0,"under_late_pressure",diag
  adj=5 if hot<=38 and momentum<=35 else 2 if hot<=50 else -5 if hot>=65 else 0
  return adj,None,diag
 if minute>=70 and hot<=28 and momentum<=25:return 0,"over_dead_late_game",diag
 adj=7 if (hot>=72 or momentum>=65) else 4 if hot>=58 else -5 if hot<=35 else 0
 return adj,None,diag
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
 sources={x[0][0] for x in sup};b2=_b2b(ctx.get("home") or "",ctx.get("away") or "",side,scope);conf=len(sources)+(1 if b2 and "1xBet" not in sources else 0);med=statistics.median(x[1] for x in sup)
 if conf<2 or med<MIN_MOVE:return None
 if persist<=0 and med<MIN_UNPERSISTED_MOVE:
  print(f"PROGRUZ_MARKET_REJECT event={eid} pick={side}{line:g} reason=unconfirmed_short_move confirms={conf} move={med:.2f}%",flush=True);return None
 minute=int(ctx.get("minute") or 0);goals=int(ctx.get("home_score") or 0)+int(ctx.get("away_score") or 0)
 if minute<=0:return None
 if scope=="FULL_TIME" and side=="UNDER" and goals>=line:return None
 if scope=="FULL_TIME" and side=="OVER" and goals>line:return None
 if scope=="FIRST_HALF" and minute>45:return None
 if scope=="SECOND_HALF" and minute<46:return None
 live_adj,reject,diag=_live_adjust(ctx,side)
 if reject:
  print(f"PROGRUZ_LIVE_REJECT event={eid} minute={minute} score={ctx.get('score')} pick={side}{line:g} reason={reject} coverage={diag['coverage']} pressure={diag['pressure']} momentum={diag['momentum']} pace={diag['pace']}",flush=True);return None
 score=round(min(100,58+min(16,conf*5)+min(14,med*3)+min(8,persist*2)+(5 if b2 else 0)+live_adj),1)
 if score<MIN_SCORE:return None
 prices=[]
 for r in own:
  try:o=float(r.get("odd"))
  except Exception:continue
  if 1.30<=o<=3.20:prices.append(o)
 if not prices:return None
 odd=max(prices);sc=f"{int(ctx.get('home_score') or 0)}:{int(ctx.get('away_score') or 0)}";res={"id":"|".join((eid,"TOTAL",scope,line_txt,side)),"event_id":eid,"home":ctx.get("home") or "","away":ctx.get("away") or "","score_live":sc,"minute":minute,"status":ctx.get("status") or "LIVE","market":"TOTAL","scope":scope,"line":line,"side":side,"odd":odd,"books":conf,"moving_sources":sorted(sources),"median_delta_pct":round(-med,3),"persistent_books":persist,"strength":score,"live_stats":ctx.get("stats") or {},"live_stats_coverage":diag["coverage"],"live_pressure":diag,"live_adjustment":live_adj,"live_truth_source":"production_live_engine_flashscore","ts":time.time()}
 print(f"PROGRUZ_TRUTH_OK event={eid} score={sc} minute={minute} pick={side}{line:g} confirms={conf} move={med:.2f}% persistent={persist} coverage={diag['coverage']} pressure={diag['pressure']} momentum={diag['momentum']} live_adj={live_adj:+d} strength={score:.0f}",flush=True);return res
def strong_rows():
 records,source,meta=_records();truth,truth_age=_truth();markets=defaultdict(list)
 for r in records:
  if not isinstance(r,dict) or str(r.get("market") or "").upper() not in {"TOTAL","OVER_UNDER"}:continue
  eid=str(r.get("event_id") or "");s=_side(r);scope=_scope(r);line=r.get("line")
  if eid and s and line is not None and scope in {"FULL_TIME","FIRST_HALF","SECOND_HALF"}:markets[(eid,scope,str(line))].append(r)
 if truth_age>LIVE_MAX_AGE:
  print(f"PROGRUZ_REJECT_ALL live_truth_stale age={truth_age:.1f}s",flush=True);return [],source,meta,len(records),len(truth),"stale_live_truth"
 by_event=defaultdict(list)
 for k,rows in markets.items():by_event[k[0]].append((k,rows))
 out=[];missing=0
 for eid,items in by_event.items():
  ctx=truth.get(eid)
  if not isinstance(ctx,dict):missing+=1;continue
  candidates=[]
  for k,rows in items:
   for side in ("OVER","UNDER"):
    c=_candidate(k,rows,side,ctx)
    if c:candidates.append(c)
  if candidates:candidates.sort(key=lambda c:(c["strength"],c["books"],abs(c["median_delta_pct"]),c["odd"]),reverse=True);out.append(candidates[0])
 out.sort(key=lambda c:(c["strength"],c["books"]),reverse=True);print(f"PROGRUZ_TRUTH cycle truth_age={truth_age:.1f}s truth_events={len(truth)} market_events={len(by_event)} missing_truth={missing} signals={len(out)}",flush=True);return out[:20],source,meta,len(records),len(truth),None
def best_bet_payload():
 d=_load(BEST_STATE);return {"ok":True,"ts":time.time(),"signal":d.get("signal") if isinstance(d.get("signal"),dict) else None}
class H(BaseHTTPRequestHandler):
 def do_GET(self):
  p=self.path.split("?",1)[0]
  if p not in ("/","/strong","/bestbet","/health","/markets"):self.send_response(404);self.end_headers();return
  if p=="/bestbet":body=best_bet_payload()
  else:
   strong,source,meta,n,truth_events,err=strong_rows();body={"ok":True,"ts":time.time(),"mode":"LIVE_TOTAL_OU_FLASH_STATS_V8_QUALITY","market_source":source,"market_records":n,"truth_events":truth_events,"truth_error":err,"min_move_pct":MIN_MOVE,"min_unpersisted_move_pct":MIN_UNPERSISTED_MOVE,"min_stats_keys":MIN_STATS_KEYS,"live_stats_gate":True,"strong":strong}
  raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
 def log_message(self,*a):return
if __name__=="__main__":print(f"GOOL_MARKET_SERVER FLASH STATS V8 QUALITY port={PORT} live_truth_max_age={LIVE_MAX_AGE}s min_move={MIN_MOVE}% min_unpersisted={MIN_UNPERSISTED_MOVE}% min_stats={MIN_STATS_KEYS} pressure_gate=on",flush=True);ThreadingHTTPServer((HOST,PORT),H).serve_forever()
