"""Broad-market BEST BET input for the Monkey market node.

Reads the last complete Monkey SQLite snapshot first. JSON remains a compatibility
fallback only. This prevents BEST BET from observing a collector file while a
new full-live cycle is still being produced.
"""
from __future__ import annotations
import json,logging,os,re,time,unicodedata,sqlite3
from difflib import SequenceMatcher
from pathlib import Path

import best_bet_engine as bbe
from fair_value import devig_odds,live_lambdas,score_matrix
from live_engine import fetch_stats,parse_stats,calculate_goal_pressure

log=logging.getLogger("best_bet_market_state")
STATE=Path(os.getenv("GOOL_MARKET_STATE","market_node_state.json"))
DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"))
MAX_STATE_AGE=max(90,int(os.getenv("GOOL_BEST_BET_MARKET_STATE_MAX_AGE","300")))
_CACHE_AT=0.0;_CACHE_ROWS=[];_CACHE_SOURCE="none"

def _f(v,d=None):
 try:return float(v)
 except Exception:return d

def _db_records():
 if not DB.exists():return []
 try:
  c=sqlite3.connect(DB,timeout=5)
  row=c.execute("SELECT id,ts,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
  if not row or time.time()-float(row[1])>MAX_STATE_AGE:return []
  return [json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))]
 except Exception as exc:
  log.info("BEST_BET_DB_READ_FAILED %s",exc);return []
 finally:
  try:c.close()
  except Exception:pass

def _json_records():
 try:d=json.loads(STATE.read_text(encoding="utf-8"))
 except Exception:return []
 if not isinstance(d,dict):return []
 lsapp=d.get("lsapp")
 if isinstance(lsapp,dict) and isinstance(lsapp.get("records"),list):return lsapp["records"]
 for key in ("records","market_records","odds","normalized_odds"):
  if isinstance(d.get(key),list):return d[key]
 return []

def _records():
 global _CACHE_AT,_CACHE_ROWS,_CACHE_SOURCE
 now=time.time()
 if _CACHE_ROWS and now-_CACHE_AT<12:return _CACHE_ROWS
 rows=_db_records();source="sqlite"
 if not rows:rows=_json_records();source="json" if rows else "none"
 _CACHE_AT=now;_CACHE_ROWS=rows;_CACHE_SOURCE=source
 return rows

def _team(v):
 s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower();s=s.replace("&"," and ")
 s=re.sub(r"\b(fc|cf|sc|afc|fk|club|football|soccer)\b"," ",s);s=re.sub(r"[^a-z0-9]+"," ",s);return " ".join(s.split())
def _sim(a,b):
 a=_team(a);b=_team(b)
 if not a or not b:return 0.0
 if a==b:return 1.0
 ta=set(a.split());tb=set(b.split());return max(len(ta&tb)/max(1,len(ta|tb)),SequenceMatcher(None,a,b).ratio())
def _score_tuple(v):
 try:a,b=str(v or "").split(":",1);return int(a),int(b)
 except Exception:return None
def _event_match(raw,m):
 eid=str(getattr(m,"event_id","") or "");rid=str(raw.get("event_id") or "")
 if eid and rid and eid==rid:return True,"event_id",1.0
 mh,ma=str(getattr(m,"home","") or ""),str(getattr(m,"away","") or "");rh,ra=str(raw.get("home") or ""),str(raw.get("away") or "")
 if not mh or not ma or not rh or not ra:return False,"none",0.0
 if _team(mh)==_team(rh) and _team(ma)==_team(ra):source="teams_exact";conf=1.0
 else:
  hs,as_=_sim(mh,rh),_sim(ma,ra);conf=(hs+as_)/2
  if hs<.78 or as_<.78 or conf<.86:return False,"none",conf
  source="teams_fuzzy"
 rs=_score_tuple(raw.get("score"));ms=(int(getattr(m,"home_score",0) or 0),int(getattr(m,"away_score",0) or 0))
 if rs is not None and sum(rs)>0 and sum(ms)>0 and abs(rs[0]-ms[0])+abs(rs[1]-ms[1])>1:return False,"score_conflict",conf
 return True,source,conf
def _norm_side(market,side):
 s=str(side or "").upper().replace(" ","")
 if market=="TOTAL":return "UNDER" if s in {"UNDER","U"} else "OVER" if s in {"OVER","O"} else s
 if market=="BTTS":return "NO" if s in {"NO","N","FALSE"} else "YES" if s in {"YES","Y","TRUE"} else s
 return s
def _normalize(raw):
 market=str(raw.get("market") or raw.get("market_raw") or "").upper();market={"HOME_DRAW_AWAY":"1X2","OVER_UNDER":"TOTAL","BOTH_TEAMS_TO_SCORE":"BTTS","DRAW_NO_BET":"DNB"}.get(market,market)
 if market not in {"1X2","TOTAL","ASIAN_HANDICAP","BTTS","DOUBLE_CHANCE","DNB"}:return None
 odd=_f(raw.get("odd"));side=_norm_side(market,raw.get("side") or raw.get("selection"))
 if not odd or odd<=1.01 or not side:return None
 flow=raw.get("flow") or {};pct=_f(flow.get("delta_pct"),0) or 0;movement=max(-12,min(12,-pct*4));status="REVERSAL" if flow.get("reversal") else "CONFIRMED_MONEY_FLOW" if pct<=-.6 and flow.get("persistence") else "PRIMARY"
 return {"scope":str(raw.get("scope") or "FULL_TIME").upper(),"market_type":market,"market":market,"selection":side,"line":_f(raw.get("line")),"odd":odd,"bookmaker":raw.get("bookmaker"),"movement_score":movement,"movement_status":status,"flow":flow,"source":_CACHE_SOURCE}
def _group_key(r):return (r.get("scope"),r.get("market_type"),r.get("line"))
def _best_rows(match):
 records=_records();matched=[];sources={};eid=str(getattr(match,"event_id","") or "");exact=[r for r in records if str(r.get("event_id") or "")==eid];candidates=exact
 if exact:sources["event_id"]=len(exact)
 else:
  candidates=[]
  for raw in records:
   ok,src,_=_event_match(raw,match)
   if ok:candidates.append(raw);sources[src]=sources.get(src,0)+1
 for raw in candidates:
  r=_normalize(raw)
  if r and r["scope"]=="FULL_TIME":matched.append(r)
 best={}
 for r in matched:
  k=(_group_key(r),r.get("selection"))
  if k not in best or r["odd"]>best[k]["odd"]:best[k]=r
 source="event_id" if exact else (max(sources,key=sources.get) if sources else "none")
 return list(best.values()),source,len(candidates)
def _outcome_probs(match,stats):
 hl,al=live_lambdas(match,stats);mat=score_matrix(hl,al);hs=int(match.home_score or 0);aw=int(match.away_score or 0);h=d=a=0
 for fh,row in enumerate(mat):
  for fa,p in enumerate(row):
   x=hs+fh;y=aw+fa
   if x>y:h+=p
   elif x==y:d+=p
   else:a+=p
 return h,d,a,mat
def _cover_prob(match,mat,side,line):
 if line is None or round(float(line)*4)%2:return None
 hs=int(match.home_score or 0);aw=int(match.away_score or 0);win=push=0
 for fh,row in enumerate(mat):
  for fa,p in enumerate(row):
   margin=(hs+fh+line-(aw+fa)) if side=="HOME" else (aw+fa+line-(hs+fh))
   if margin>1e-9:win+=p
   elif abs(margin)<=1e-9:push+=p
 return win+.5*push
def _model_probability(row,match,stats):
 k=str(row.get("market_type") or "").upper();s=str(row.get("selection") or "").upper()
 if k in {"TOTAL","BTTS"}:return bbe._legacy_model_probability(row,match,stats)
 h,d,a,mat=_outcome_probs(match,stats)
 if k=="1X2":return h if s=="HOME" else d if s=="DRAW" else a if s=="AWAY" else None
 if k=="DNB":
  den=h+a;return None if den<=0 else h/den if s=="HOME" else a/den if s=="AWAY" else None
 if k=="DOUBLE_CHANCE":
  return h+d if s in {"1X","HOME_DRAW","HOMEDRAW"} else d+a if s in {"X2","DRAW_AWAY","DRAWAWAY"} else h+a if s in {"12","HOME_AWAY","HOMEAWAY"} else None
 if k=="ASIAN_HANDICAP":return _cover_prob(match,mat,s,_f(row.get("line"))) if s in {"HOME","AWAY"} else None
 return None
def _fair_probs(rows):
 groups={}
 for r in rows:groups.setdefault(_group_key(r),[]).append(r)
 for grp in groups.values():
  k=str(grp[0].get("market_type") or "");expected=3 if k=="1X2" else 2 if k in {"TOTAL","BTTS","DNB"} else 0
  if expected and len(grp)>=expected:
   probs=devig_odds([x["odd"] for x in grp])
   if len(probs)==len(grp):
    for x,p in zip(grp,probs):x["market_fair_prob"]=p;x["pair_confirmed"]=True
  else:
   for x in grp:x["market_fair_prob"]=1/x["odd"];x["pair_confirmed"]=False
def _rank_market(row,m,p,hist):
 try:return bbe._rank(row,m,p,hist)
 except TypeError as exc:
  if "positional arguments" not in str(exc):raise
  return bbe._rank(row,m,p)
def evaluate_match(m):
 eid=str(m.event_id);now=time.time()
 if bbe._pending(eid) or (eid in bbe._ACTIVE and now-bbe._ACTIVE[eid]<bbe.COOLDOWN):return False
 rows,match_src,raw_n=_best_rows(m)
 if not rows:log.info("BEST_BET_STATE %s rows=0 match=%s raw=%d store=%s teams=%s--%s",eid,match_src,raw_n,_CACHE_SOURCE,m.home,m.away);return False
 try:
  body=fetch_stats(eid);stats=parse_stats(body) if body else {}
  if not stats:return False
  p=calculate_goal_pressure(m,stats,None);hist=bbe._history(m)
 except Exception as exc:log.info("BEST_BET_STATE input unavailable %s %s",eid,exc);return False
 _fair_probs(rows);ranked=[]
 for r in rows:
  try:r["gool_model_prob"]=_model_probability(r,m,stats)
  except Exception:r["gool_model_prob"]=None
  if r.get("gool_model_prob") is None:continue
  x=_rank_market(r,m,p,hist)
  if x:ranked.append(x)
 ranked.sort(key=lambda x:x["score"],reverse=True)
 if not ranked:log.info("BEST_BET_STATE %s rows=%d ranked=0 match=%s store=%s history=%s",eid,len(rows),match_src,_CACHE_SOURCE,hist);return False
 b=ranked[0];log.info("BEST_BET_STATE %s rows=%d ranked=%d match=%s store=%s best=%s score=%.1f live=%.1f history=%.1f edge=%+.1f flow=%.1f status=%s",eid,len(rows),len(ranked),match_src,_CACHE_SOURCE,b["name"],b["score"],b["confidence"],b["history_score"],b["edge"],b["market_score"],b["status"])
 if b["score"]<bbe.MIN_SCORE or b["suspicious"]:return False
 if not bbe._record(m,b):return False
 sent=bbe._send(bbe.render_entry(m,b,ranked[1:4]),f"🏆 GOOL BEST BET • {b['name']} @ {b['odd']:.2f} • {b['score']:.0f}/100")
 if sent:bbe._ACTIVE[eid]=now;log.info("BEST_BET_SENT %s %s score=%.1f edge=%+.1f source=%s match=%s",eid,b["name"],b["score"],b["edge"],_CACHE_SOURCE,match_src)
 return sent
if not hasattr(bbe,"_legacy_model_probability"):bbe._legacy_model_probability=bbe.model_probability
bbe.evaluate_match=evaluate_match
log.info("BEST BET market server input active | sqlite=%s json_fallback=%s | 1X2+TOTAL+AH+BTTS+DC+DNB",DB,STATE)
