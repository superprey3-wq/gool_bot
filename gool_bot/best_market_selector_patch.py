"""Rank verified GOOL CORE full-time markets and mark one concrete best bet.

CORE 2.0 market probability is market-specific. Match goal probability must
never be reused as probability for BTTS or a team total. Team totals and BTTS
are gated by side-specific LIVE evidence.
"""
from __future__ import annotations
import math
import live_candidate_patch as lc
import unified_bot
import market_movement
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
def _stats(p):return getattr(p,"stats",None) or getattr(p,"raw_stats",None) or {}
def _side(row):return 0 if str(row.get("team_side"))=="HOME" or str(row.get("market_type"))=="TEAM_TOTAL_HOME" else 1
def _goals_needed(row,m):
 side=_side(row);current=int(m.home_score if side==0 else m.away_score)
 try:line=float(row.get("line"))
 except:return 1
 return max(1,int(math.floor(line))+1-current)
def _side_live_evidence(st,side):
 xg=_pair(st,"xg")[side];xgot=_pair(st,"xgot")[side];sot=_pair(st,"shots_on_target")[side];ibox=_pair(st,"shots_inside_box")[side];touch=_pair(st,"touches_box")[side];big=_pair(st,"big_chances")[side];shots=_pair(st,"shots")[side]
 evidence=sum((xg>=.25,xgot>=.18,sot>=1,ibox>=2,touch>=5,big>=1,shots>=4));available=any(v>0 for v in (xg,xgot,sot,ibox,touch,big,shots))
 return {"xg":xg,"xgot":xgot,"sot":sot,"ibox":ibox,"touch":touch,"big":big,"shots":shots,"evidence":evidence,"available":available}
def _team_evidence(row,m,p):
 ev=_side_live_evidence(_stats(p),_side(row));ev["needed"]=_goals_needed(row,m);return ev
def _team_conf(row,m,p):
 ev=_team_evidence(row,m,p);side=_side(row);st=_stats(p);threat=0.;weight=0.
 for k,w in (("xg",30),("xgot",20),("shots_on_target",8),("shots_inside_box",3),("touches_box",.7),("big_chances",12)):
  a,b=_pair(st,k);vals=(a,b);threat+=vals[side]*w;weight+=max(vals)*w
 share=.5 if weight<=0 else max(.15,min(.85,threat/weight));market=_implied(row.get("odd"));pressure=float(getattr(p,"score",0) or 0);need_penalty=max(0,ev["needed"]-1)*18
 conf=market*.38+pressure*.24+(share*100)*.28+ev["evidence"]*2.0-need_penalty
 return max(5.,min(88.,conf))
def _team_allowed(row,m,p):
 ev=_team_evidence(row,m,p)
 if not ev["available"]:return False,"NO_TEAM_STATS",ev
 minimum=3 if ev["needed"]>=2 else 2
 if ev["evidence"]<minimum:return False,"LOW_TEAM_EVIDENCE",ev
 return True,"OK",ev
def _btts_context(row,m,p):
 hs=int(m.home_score or 0);as_=int(m.away_score or 0)
 if hs>0 and as_>0:return True,"ALREADY_BTTS",None
 if hs==0 and as_==0:return True,"BOTH_NEED_SCORE",None
 missing=0 if hs==0 else 1;ev=_side_live_evidence(_stats(p),missing)
 if not ev["available"]:return False,"NO_BTTS_TEAM_STATS",ev
 if ev["evidence"]<2:return False,"LOW_BTTS_TEAM_EVIDENCE",ev
 return True,"OK",ev
def _model_conf(row,m,p):
 try:
  kind=str(row.get("market_type") or "TOTAL")
  if kind.startswith("TEAM_TOTAL"):return _team_conf(row,m,p)
  odd=float(row["odd"])
  if kind=="BTTS":
   market=_implied(odd);pressure=float(getattr(p,"score",0) or 0);mom=float(getattr(p,"momentum",0) or 0);hs=int(m.home_score or 0);as_=int(m.away_score or 0);one=(hs>0) ^ (as_>0)
   if one:
    missing=0 if hs==0 else 1;ev=_side_live_evidence(_stats(p),missing);team_bonus=min(12.,ev["xg"]*8+ev["sot"]*2+ev["shots"]*.5);return max(5.,min(88.,market*.42+pressure*.28+mom*.15+team_bonus))
   return max(5.,min(84.,market*.45+pressure*.30+mom*.15))
  if row.get("confidence") is not None:return float(row["confidence"])
 except:pass
 return float(getattr(p,"score",0) or 0)*.65
def _rank(r,m,p):
 try:odd=float(r["odd"])
 except:return -999.,{}
 kind=str(r.get("market_type") or "TOTAL")
 if kind.startswith("TEAM_TOTAL"):
  allowed,why,ev=_team_allowed(r,m,p);r["team_market_gate"]=why;r["team_goals_needed"]=ev["needed"];r["team_evidence"]=ev["evidence"]
  if not allowed:return -999.,{"selector_reject":why,"team_goals_needed":ev["needed"],"team_evidence":ev["evidence"]}
 if kind=="BTTS":
  allowed,why,ev=_btts_context(r,m,p);r["btts_market_gate"]=why
  if not allowed:return -999.,{"selector_reject":why,"btts_evidence":ev.get("evidence") if ev else None}
 conf=_model_conf(r,m,p);imp=_implied(odd);edge=conf-imp;r["value_edge"]=round(edge,1);sources=int(r.get("source_count") or r.get("bookmakers") or 1);movement=float(r.get("movement_score") or 0.0);score=conf*.58+max(-15.,min(20.,edge))*.65+_confirmation(r)+_price(odd)+min(6.,max(0,sources-1)*3.)+movement
 if kind in {"BTTS","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and sources<2:score-=5.
 if kind=="BTTS" and int(m.minute or 0)>=75:score-=5.
 if str(r.get("external_market_status") or r.get("market_status") or "") in {"CONFLICT","DISAGREE"}:score-=4.
 return score,{"selector_score":round(score,1),"selector_confidence":round(conf,1),"selector_implied":round(imp,1),"selector_edge":round(edge,1),"selector_movement":round(movement,1),"team_goals_needed":r.get("team_goals_needed"),"team_evidence":r.get("team_evidence")}
def _market(entries,m,p):
 recs,market=_orig_market(entries,m,p);market_movement.annotate(recs)
 for r in recs:r.pop("best_concrete_bet",None)
 ranked=[]
 for r in recs:
  if r.get("scope")!="FULL_TIME" or r.get("odd") is None:continue
  kind=str(r.get("market_type") or "TOTAL")
  if kind not in {"TOTAL","BTTS","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"} and r.get("goal_step") is None:continue
  score,meta=_rank(r,m,p);r.update(meta)
  if score>-900:ranked.append((score,r))
 ranked.sort(key=lambda x:x[0],reverse=True)
 if ranked:
  best=ranked[0][1];best["best_concrete_bet"]=True
  market["best_concrete_bet"]={k:best.get(k) for k in ("scope","market_type","extra_market","team_side","team_name","line","selection","odd","source","source_prices","selector_score","selector_confidence","selector_implied","selector_edge","selector_movement","movement_status","movement_drop_pct","correlated_steam","market_status","team_goals_needed","team_evidence","btts_market_gate")}
  market["best_alternatives"]=[{k:r.get(k) for k in ("scope","market_type","team_name","line","selection","odd","source","selector_score","selector_confidence","selector_edge","selector_movement","movement_status","team_goals_needed","team_evidence","btts_market_gate")} for _,r in ranked[1:3]]
 else:
  market.pop("best_concrete_bet",None);market["best_alternatives"]=[]
 return recs,market
lc._market=_market
