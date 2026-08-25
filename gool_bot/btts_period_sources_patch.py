"""Candidate-only confirmation for BTTS Yes and dynamic first-half goal totals.

Bovada is intentionally disabled. These auxiliary markets now use the verified
Kambi/BetRivers feed only. The 1H market follows the current score dynamically.
"""
from __future__ import annotations
import time
from collections import defaultdict,deque
import live_candidate_patch as lc
from kambi_live_odds import get_btts_yes as kam_btts,get_live_goal_totals as kam_totals
_orig_market=lc._market
_orig_format=lc._format_strategy_signal
_HISTORY:dict[str,deque]=defaultdict(lambda:deque(maxlen=4));_TTL=45*60

def _track(key,odd):
 now=time.time();q=_HISTORY[key]
 while q and now-q[0][0]>_TTL:q.popleft()
 if not q or abs(float(q[-1][1])-float(odd))>1e-6 or now-q[-1][0]>=20:q.append((now,float(odd)))
 if len(q)<2:return {"direction":"flat","from":round(float(odd),3),"to":round(float(odd),3),"drop_pct":0.0}
 old,new=float(q[0][1]),float(q[-1][1]);drop=(old-new)/old*100 if old>1 else 0
 return {"direction":"toward" if drop>.5 else "against" if drop<-.5 else "flat","from":round(old,3),"to":round(new,3),"drop_pct":round(drop,2)}

def _pack(event_id,kind,rows,line=None):
 clean=[]
 for row in rows:
  if not row:continue
  try:odd=float(row.get("odd"))
  except Exception:continue
  if odd<=1.001:continue
  source=str(row.get("source") or "LIVE");clean.append({"source":source,"odd":odd,"movement":_track(f"{event_id}|{kind}|{line}|{source}",odd)})
 if not clean:return None
 vals=[x["odd"] for x in clean]
 return {"market_type":kind,"line":line,"source_prices":clean,"source_count":len(clean),"source_spread_pct":0.0,"market_status":"SINGLE_SOURCE","best_odd":round(max(vals),3)}

def _dynamic_first_half(m):
 if int(m.minute or 0)>45 or m.is_halftime:return None
 goals=int(m.home_score or 0)+int(m.away_score or 0);target=goals+.5
 try:krows=kam_totals(m.home,m.away)
 except Exception:krows=[]
 k=next((r for r in krows if r.get("scope")=="FIRST_HALF" and abs(float(r.get("line",-99))-target)<1e-9),None)
 return _pack(m.event_id,"FIRST_HALF_GOAL",[k],target)

def _side_markets(m):
 out=[]
 if not (int(m.home_score or 0)>0 and int(m.away_score or 0)>0):
  try:b=_pack(m.event_id,"BTTS",[kam_btts(m.home,m.away)])
  except Exception:b=None
  if b:out.append(b)
 h=_dynamic_first_half(m)
 if h:out.append(h)
 return out

def _market(entries,m,p):
 recs,market=_orig_market(entries,m,p)
 try:side=_side_markets(m)
 except Exception:side=[]
 if side:
  market["side_markets"]=side
  for x in side:
   rr={"scope":"FIRST_HALF" if x["market_type"]=="FIRST_HALF_GOAL" else "FULL_TIME","market_type":x["market_type"],"extra_market":"FIRST_HALF_DYNAMIC" if x["market_type"]=="FIRST_HALF_GOAL" else "BTTS_YES","odd":x["best_odd"],"source":"Kambi/BetRivers","source_prices":x["source_prices"],"market_status":x["market_status"],"source_count":x["source_count"],"source_spread_pct":x["source_spread_pct"]}
   if x["market_type"]=="FIRST_HALF_GOAL":rr.update({"line":float(x["line"]),"selection":"OVER"})
   else:rr.update({"selection":"YES"})
   recs.append(rr)
 return recs,market

def _fmt_sources(row):return " | ".join(f"{x['source']} {float(x['odd']):.2f}" for x in row.get("source_prices") or [])
def _format(m,p,s,recs,goals,reason,route,master,hz,market):
 base=_orig_format(m,p,s,recs,goals,reason,route,master,hz,market);side=(market or {}).get("side_markets") or []
 if not side:return base
 lines=["","🎯 <b>ДОП. LIVE-РЫНКИ</b>"]
 for x in side:
  prices=_fmt_sources(x);label="Обе забьют — Да" if x.get("market_type")=="BTTS" else f"Гол до перерыва · ТБ{float(x.get('line',.5)):g} 1Т"
  lines.append(f"🟡 <b>{label}</b>: {prices} · SINGLE_SOURCE")
 return base+"\n"+"\n".join(lines)
lc._market=_market
lc._format_strategy_signal=_format
