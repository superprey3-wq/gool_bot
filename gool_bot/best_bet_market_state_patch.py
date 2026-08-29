"""Broad-market BEST BET input for Monkey SQLite market state.

Uses the already-synchronised Flashscore truth stats carried on the match object. This
avoids a second stats request per event and makes BEST BET analyse the exact same live
snapshot as PROGRUZ. Detailed rejection diagnostics explain why a pick did not fire.
"""
from __future__ import annotations
import json,logging,os,re,time,unicodedata,sqlite3
from difflib import SequenceMatcher
from pathlib import Path
import best_bet_engine as bbe
from fair_value import devig_odds,live_lambdas,score_matrix
from live_engine import calculate_goal_pressure
log=logging.getLogger("best_bet_market_state")
STATE=Path(os.getenv("GOOL_MARKET_STATE","market_node_state.json"));DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"));MAX_STATE_AGE=max(90,int(os.getenv("GOOL_BEST_BET_MARKET_STATE_MAX_AGE","300")))
_CACHE_AT=0.;_CACHE_ROWS=[];_CACHE_SOURCE="none"
def _f(v,d=None):
 try:return float(v)
 except Exception:return d
def _db_records():
 if not DB.exists():return []
 c=None
 try:
  c=sqlite3.connect(DB,timeout=5);row=c.execute("SELECT id,ts,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
  if not row or time.time()-float(row[1])>MAX_STATE_AGE:return []
  return [json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))]
 except Exception as exc:log.info("BEST_BET_DB_READ_FAILED %s",exc);return []
 finally:
  if c:
   try:c.close()
   except Exception:pass
def _json_records():
 try:d=json.loads(STATE.read_text(encoding="utf-8"))
 except Exception:return []
 ls=d.get("lsapp") if isinstance(d,dict) else None
 if isinstance(ls,dict) and isinstance(ls.get("records"),list):return ls["records"]
 return []
def _records():
 global _CACHE_AT,_CACHE_ROWS,_CACHE_SOURCE
 if _CACHE_ROWS and time.time()-_CACHE_AT<12:return _CACHE_ROWS
 rows=_db_records();_CACHE_SOURCE="sqlite"
 if not rows:rows=_json_records();_CACHE_SOURCE="json" if rows else "none"
 _CACHE_AT=time.time();_CACHE_ROWS=rows;return rows
def _team(v):
 s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower();s=re.sub(r"\b(fc|cf|sc|afc|fk|club|football|soccer)\b"," ",s);return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())
def _sim(a,b):
 a=_team(a);b=_team(b);return 0. if not a or not b else 1. if a==b else max(len(set(a.split())&set(b.split()))/max(1,len(set(a.split())|set(b.split()))),SequenceMatcher(None,a,b).ratio())
def _event_match(raw,m):
 eid=str(getattr(m,"event_id","") or "");rid=str(raw.get("event_id") or "")
 if eid and rid and eid==rid:return True,"event_id",1.
 hs,as_=_sim(getattr(m,"home",""),raw.get("home")),_sim(getattr(m,"away",""),raw.get("away"));return (hs>=.78 and as_>=.78 and (hs+as_)/2>=.86),"teams_fuzzy",(hs+as_)/2
def _norm_side(market,side):
 s=str(side or "").upper().replace(" ","")
 if market=="TOTAL":return "UNDER" if s in {"UNDER","U"} else "OVER" if s in {"OVER","O"} else s
 if market=="BTTS":return "NO" if s in {"NO","N","FALSE"} else "YES" if s in {"YES","Y","TRUE"} else s
 return s
def _normalize(raw):
 market=str(raw.get("market") or raw.get("market_raw") or "").upper();market={"HOME_DRAW_AWAY":"1X2","OVER_UNDER":"TOTAL","BOTH_TEAMS_TO_SCORE":"BTTS"}.get(market,market)
 if market not in {"1X2","TOTAL","ASIAN_HANDICAP","BTTS","DOUBLE_CHANCE","DNB"}:return None
 odd=_f(raw.get("odd"));side=_norm_side(market,raw.get("side") or raw.get("selection"))
 if not odd or odd<=1.01 or not side:return None
 flow=raw.get("flow") or {};pct=_f(flow.get("delta_pct"),0) or 0;movement=max(-12,min(12,-pct*4));status="REVERSAL" if flow.get("reversal") else "CONFIRMED_MONEY_FLOW" if pct<=-.6 and flow.get("persistence") else "PRIMARY"
 return {"scope":str(raw.get("scope") or "FULL_TIME").upper(),"market_type":market,"market":market,"selection":side,"line":_f(raw.get("line")),"odd":odd,"bookmaker":raw.get("bookmaker"),"movement_score":movement,"movement_status":status,"flow":flow,"source":_CACHE_SOURCE}
def _group_key(r):return (r.get("scope"),r.get("market_type"),r.get("line"))
def _best_rows(m):
 records=_records();eid=str(getattr(m,"event_id","") or "");exact=[r for r in records if str(r.get("event_id") or "")==eid];cand=exact
 if not cand:cand=[r for r in records if _event_match(r,m)[0]]
 matched=[x for raw in cand if (x:=_normalize(raw)) and x["scope"]=="FULL_TIME"]
 best={}
 for r in matched:
  k=(_group_key(r),r["selection"])
  if k not in best or r["odd"]>best[k]["odd"]:best[k]=r
 return list(best.values()),("event_id" if exact else "teams_fuzzy" if cand else "none"),len(cand)
def _outcome_probs(match,stats):
 hl,al=live_lambdas(match,stats);mat=score_matrix(hl,al);hs=int(match.home_score or 0);aw=int(match.away_score or 0);h=d=a=0
 for fh,row in enumerate(mat):
  for fa,p in enumerate(row):
   x=hs+fh;y=aw+fa
   if x>y:h+=p
   elif x==y:d+=p
   else:a+=p
 return h,d,a,mat
def _model_probability(row,m,stats):
 k=str(row.get("market_type") or "").upper();s=str(row.get("selection") or "").upper()
 if k in {"TOTAL","BTTS"}:return bbe._legacy_model_probability(row,m,stats)
 h,d,a,_=_outcome_probs(m,stats)
 if k=="1X2":return h if s=="HOME" else d if s=="DRAW" else a if s=="AWAY" else None
 return None
def _fair_probs(rows):
 groups={}
 for r in rows:groups.setdefault(_group_key(r),[]).append(r)
 for grp in groups.values():
  expected=3 if grp[0]["market_type"]=="1X2" else 2 if grp[0]["market_type"] in {"TOTAL","BTTS","DNB"} else 0
  if expected and len(grp)>=expected:
   probs=devig_odds([x["odd"] for x in grp])
   if len(probs)==len(grp):
    for x,p in zip(grp,probs):x["market_fair_prob"]=p;x["pair_confirmed"]=True
def _rank_market(row,m,p,hist):
 try:return bbe._rank(row,m,p,hist)
 except TypeError:return bbe._rank(row,m,p)
def evaluate_match(m):
 eid=str(m.event_id);now=time.time()
 if bbe._pending(eid) or (eid in bbe._ACTIVE and now-bbe._ACTIVE[eid]<bbe.COOLDOWN):return False
 rows,src,raw_n=_best_rows(m)
 if not rows:log.info("BEST_BET_REJECT event=%s reason=no_market_rows raw=%d store=%s",eid,raw_n,_CACHE_SOURCE);return False
 stats=getattr(m,"stats",None) or getattr(m,"raw_stats",None) or ((getattr(m,"analysis_context",None) or {}).get("live_stats") if isinstance(getattr(m,"analysis_context",None),dict) else None) or {}
 if not stats:log.info("BEST_BET_REJECT event=%s reason=no_truth_stats rows=%d",eid,len(rows));return False
 try:p=calculate_goal_pressure(m,stats,None);hist=bbe._history(m)
 except Exception as exc:log.info("BEST_BET_REJECT event=%s reason=analysis_error err=%s",eid,type(exc).__name__);return False
 _fair_probs(rows);ranked=[];modelled=0
 for r in rows:
  try:r["gool_model_prob"]=_model_probability(r,m,stats)
  except Exception:r["gool_model_prob"]=None
  if r.get("gool_model_prob") is None:continue
  modelled+=1;x=_rank_market(r,m,p,hist)
  if x:ranked.append(x)
 ranked.sort(key=lambda x:x["score"],reverse=True)
 if not ranked:log.info("BEST_BET_REJECT event=%s reason=no_ranked rows=%d modelled=%d source=%s",eid,len(rows),modelled,src);return False
 b=ranked[0];log.info("BEST_BET_CANDIDATE event=%s score=%s:%s minute=%s market=%s odd=%.2f master=%.1f live=%.1f history=%.1f edge=%+.1f flow=%.1f status=%s suspicious=%s rows=%d",eid,m.home_score,m.away_score,m.minute,b["name"],b["odd"],b["score"],b["confidence"],b["history_score"],b["edge"],b["market_score"],b["status"],b["suspicious"],len(rows))
 if b["score"]<bbe.MIN_SCORE:log.info("BEST_BET_REJECT event=%s reason=score master=%.1f threshold=%.1f",eid,b["score"],bbe.MIN_SCORE);return False
 if b["suspicious"]:log.info("BEST_BET_REJECT event=%s reason=suspicious edge=%+.1f ev=%s",eid,b["edge"],b.get("ev_pct"));return False
 if not bbe._record(m,b):log.info("BEST_BET_REJECT event=%s reason=journal_record",eid);return False
 sent=bbe._send(bbe.render_entry(m,b,ranked[1:4]),f"🏆 GOOL BEST BET • {b['name']} @ {b['odd']:.2f} • {b['score']:.0f}/100")
 if sent:bbe._ACTIVE[eid]=now;log.info("BEST_BET_SENT %s %s score=%.1f edge=%+.1f source=%s",eid,b["name"],b["score"],b["edge"],src)
 return sent
if not hasattr(bbe,"_legacy_model_probability"):bbe._legacy_model_probability=bbe.model_probability
bbe.evaluate_match=evaluate_match
log.info("BEST BET Monkey truth input V2 | sqlite=%s | uses preloaded Flashscore stats | diagnostics=on",DB)
