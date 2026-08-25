"""Rank verified GOOL CORE full-time markets and mark one concrete best bet.

FIRST_HALF markets stay visible on the card but are handled by the dedicated
FIRST_HALF_GOAL strategy, so CORE never stores a period bet it cannot audit from
final match data. CORE ranks: match Over, BTTS Yes, home/away Team Total Over.
"""
from __future__ import annotations
import live_candidate_patch as lc
import unified_bot
_orig_market=lc._market

def _implied(odd):
 try:return max(1.0,min(99.0,100.0/float(odd)))
 except:return 0.0

def _confirmation(r):
 s=str(r.get("external_market_status") or r.get("market_status") or r.get("market_consensus") or "")
 return {"STEAM":12.,"CONFIRMED":8.,"EARLY":1.,"SINGLE_SOURCE":-2.,"DISAGREE":-9.,"CONFLICT":-14.}.get(s,0.)
def _price(odd):
 try:o=float(odd)
 except:return -20.
 if o<1.05 or o>6:return -20.
 if 1.35<=o<=2.40:return 5.
 if 1.20<=o<1.35 or 2.40<o<=3.20:return 2.
 if o>4:return -5.
 return 0.
def _pair(st,k):
 try:a,b=st.get(k,(0,0));return float(a or 0),float(b or 0)
 except:return 0.,0.
def _team_conf(row,m,p):
 side=0 if str(row.get("team_side"))=="HOME" else 1;st=getattr(p,"stats",None) or getattr(p,"raw_stats",None) or {};threat=0.;weight=0.
 for k,w in (("xg",30),("xgot",20),("shots_on_target",8),("shots_inside_box",3),("touches_box",.7),("big_chances",12)):
  a,b=_pair(st,k);vals=(a,b);threat+=vals[side]*w;weight+=max(vals)*w
 share=.5 if weight<=0 else max(.15,min(.85,threat/weight));market=_implied(row.get("odd"));pressure=float(getattr(p,"score",0) or 0);current=int(m.home_score if side==0 else m.away_score);bonus=5 if current==0 else 2
 return max(5.,min(91.,market*.42+pressure*.30+(share*100)*.28+bonus))
def _model_conf(row,m,p):
 try:
  if row.get("confidence") is not None:return float(row["confidence"])
  odd=float(row["odd"]);kind=str(row.get("market_type") or "TOTAL")
  if kind.startswith("TEAM_TOTAL"):return _team_conf(row,m,p)
  if kind=="BTTS":
   market=_implied(odd);pressure=float(getattr(p,"score",0) or 0);mom=float(getattr(p,"momentum",0) or 0);one=(int(m.home_score or 0)>0) ^ (int(m.away_score or 0)>0)
   return max(5.,min(88.,market*.45+pressure*.35+mom*.20+(5 if one else 0)))
 except:pass
 return float(getattr(p,"score",0) or 0)*.65
def _rank(r,m,p):
 try:odd=float(r["odd"])
 except:return -999.,{}
 conf=_model_conf(r,m,p);imp=_implied(odd);edge=float(r.get("value_edge") if r.get("value_edge") is not None else conf-imp);sources=int(r.get("source_count") or r.get("bookmakers") or 1);score=conf*.58+max(-15.,min(20.,edge))*.65+_confirmation(r)+_price(odd)+min(6.,max(0,sources-1)*3.)
 kind=str(r.get("market_type") or "TOTAL")
 if kind in {"BTTS","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and sources<2:score-=5.
 if kind=="BTTS" and int(m.minute or 0)>=75:score-=5.
 if str(r.get("external_market_status") or r.get("market_status") or "") in {"CONFLICT","DISAGREE"}:score-=4.
 return score,{"selector_score":round(score,1),"selector_confidence":round(conf,1),"selector_implied":round(imp,1),"selector_edge":round(edge,1)}
def _market(entries,m,p):
 recs,market=_orig_market(entries,m,p)
 for r in recs:r.pop("best_concrete_bet",None)
 ranked=[]
 for r in recs:
  # Dedicated 1H strategy owns period bets; CORE selects only auditable full-time markets.
  if r.get("scope")!="FULL_TIME" or r.get("odd") is None:continue
  kind=str(r.get("market_type") or "TOTAL")
  if kind not in {"TOTAL","BTTS","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and r.get("goal_step") is None:continue
  score,meta=_rank(r,m,p);r.update(meta)
  if score>-900:ranked.append((score,r))
 ranked.sort(key=lambda x:x[0],reverse=True)
 if ranked:
  best=ranked[0][1];best["best_concrete_bet"]=True
  market["best_concrete_bet"]={k:best.get(k) for k in ("scope","market_type","extra_market","team_side","team_name","line","selection","odd","source","source_prices","selector_score","selector_confidence","selector_edge","market_status")}
  market["best_alternatives"]=[{k:r.get(k) for k in ("scope","market_type","team_name","line","selection","odd","source","selector_score")} for _,r in ranked[1:3]]
 return recs,market
lc._market=_market
