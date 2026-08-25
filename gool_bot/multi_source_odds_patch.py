"""Candidate-only LIVE totals confirmation from LSApp/Flashscore + Kambi.

Bovada is intentionally disabled. CORE totals are rebuilt only from the exact
same line exposed by LSApp/Flashscore and/or Kambi/BetRivers. No synthetic
average is used; the selected quote is an actual source price. Raw normalized
source prices are logged for audit.
"""
from __future__ import annotations
import logging,time
from collections import defaultdict,deque
import live_candidate_patch as lc
import unified_bot
from kambi_live_odds import get_live_goal_totals
logger=logging.getLogger("multi_source_odds")
_HISTORY:dict[str,deque]=defaultdict(lambda:deque(maxlen=4));_TTL=45*60

def _standard(line):
 try:return abs(float(line)*2-round(float(line)*2))<1e-9
 except:return False
def _track(key,odd):
 now=time.time();q=_HISTORY[key]
 while q and now-q[0][0]>_TTL:q.popleft()
 if not q or abs(q[-1][1]-float(odd))>1e-6 or now-q[-1][0]>=20:q.append((now,float(odd)))
 if len(q)<2:return {"direction":"flat","from":round(float(odd),3),"to":round(float(odd),3),"drop_pct":0.0}
 old,new=float(q[0][1]),float(q[-1][1]);drop=(old-new)/old*100 if old>1 else 0.0
 return {"direction":"toward" if drop>.5 else "against" if drop<-.5 else "flat","from":round(old,3),"to":round(new,3),"drop_pct":round(drop,2)}
def _sane(row):return lc._sane_price(row) and _standard(float(row.get("line",-99)))
def _lsapp(entries,m,p,targets):
 rows=[]
 try:base=unified_bot._recommendations(entries,m,p)
 except Exception:return rows
 for r in base:
  try:line=float(r.get("line"));odd=float(r.get("odd"))
  except Exception:continue
  if r.get("scope")=="FULL_TIME" and line in targets and _sane({"line":line,"odd":odd}):rows.append({"scope":"FULL_TIME","line":line,"odd":odd,"source":"LSApp","bookmakers":int(r.get("bookmakers") or 1)})
 return rows
def _choose_actual_source(sources):
 ordered=sorted(sources,key=lambda x:float(x["odd"]))
 # With two sources use the more conservative lower quote; with one use it directly.
 return ordered[0]
def _target_with_multi(entries,m,p):
 goals=int(m.home_score or 0)+int(m.away_score or 0);targets=(float(goals+.5),float(goals+1.5));by=defaultdict(list)
 for r in _lsapp(entries,m,p,targets):by[float(r["line"])].append(r)
 try:
  for r in get_live_goal_totals(m.home,m.away):
   if r.get("scope")=="FULL_TIME" and float(r.get("line",-99)) in targets and _sane(r):by[float(r["line"])].append(dict(r,source="Kambi/BetRivers"))
 except Exception as exc:logger.info("ODDS_KAMBI_FAILED %s %s",m.event_id,exc)
 out=[];now=time.time()
 for step,line in enumerate(targets,1):
  raw=by.get(line,[]);dedup={}
  for x in raw:
   try:odd=float(x["odd"]);src=str(x.get("source") or "LIVE")
   except Exception:continue
   dedup[src]={"source":src,"odd":odd,"movement":_track(f"{m.event_id}|TOTAL|{line:g}|{src}",odd)}
  sources=list(dedup.values())
  if not sources:continue
  anchor=_choose_actual_source(sources);vals=[float(x["odd"]) for x in sources];spread=(max(vals)-min(vals))/min(vals)*100 if len(vals)>=2 and min(vals)>0 else 0.0
  toward=sum(x["movement"]["direction"]=="toward" for x in sources);against=sum(x["movement"]["direction"]=="against" for x in sources)
  consensus="CONFIRMED" if len(sources)>=2 and spread<=12 else "DISAGREE" if len(sources)>=2 else "SINGLE_SOURCE"
  movement="STEAM" if len(sources)>=2 and toward>=2 else "CONFLICT" if against>toward else "EARLY"
  odd=float(anchor["odd"]);conf=unified_bot._model_confidence(p.score,p.momentum,line,goals,"FULL_TIME",m.minute,odd)
  row={"scope":"FULL_TIME","market_type":"TOTAL","selection":"OVER","line":line,"odd":odd,"source":anchor["source"],"source_prices":sources,"source_count":len(sources),"bookmakers":len(sources),"market_consensus":consensus,"market_status":consensus,"external_market_status":movement,"source_spread_pct":round(spread,2),"quote_ts":now,"goal_step":step,"target_label":"ещё 1 гол" if step==1 else "ещё 2 гола","confidence":conf,"value_edge":round(conf-(100/odd),1)}
  logger.info("ODDS_MAP event=%s match=%s-%s line=%.1f sources=%s selected=%s@%.3f spread=%.1f%% consensus=%s",m.event_id,m.home,m.away,line,[(x['source'],round(float(x['odd']),3)) for x in sources],anchor['source'],odd,spread,consensus)
  out.append(row)
 if out:
  best=max(out,key=lambda r:(float(r.get("value_edge",-999)),int(r.get("confidence",0)),-int(r.get("goal_step",9))));best["best_bet"]=True
 return out
lc._target_goal_markets=_target_with_multi
logger.info("Bovada disabled | CORE totals sources: LSApp + Kambi/BetRivers")
