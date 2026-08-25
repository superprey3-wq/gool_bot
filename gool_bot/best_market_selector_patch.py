"""GOOL CORE 2.0 market selector.

Every candidate is evaluated against the exact settlement condition of that
market. Generic P(next goal) is never reused for a market that needs multiple
goals, BTTS, or a team total.
"""
from __future__ import annotations
import math
import live_candidate_patch as lc
import market_movement
_orig_market=lc._market

def _implied(odd):
 try:return max(1.0,min(99.0,100.0/float(odd)))
 except:return 0.0

def _confirmation(r):
 s=str(r.get('external_market_status') or r.get('market_status') or r.get('market_consensus') or '')
 return {'STEAM':12.,'CONFIRMED':8.,'EARLY':1.,'SINGLE_SOURCE':-2.,'DISAGREE':-9.,'CONFLICT':-14.}.get(s,0.)

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
def _stats(p):return getattr(p,'stats',None) or getattr(p,'raw_stats',None) or {}
def _side(row):return 0 if str(row.get('team_side'))=='HOME' or str(row.get('market_type'))=='TEAM_TOTAL_HOME' else 1

def _side_live_evidence(st,side):
 xg=_pair(st,'xg')[side];xgot=_pair(st,'xgot')[side];sot=_pair(st,'shots_on_target')[side];ibox=_pair(st,'shots_inside_box')[side];touch=_pair(st,'touches_box')[side];big=_pair(st,'big_chances')[side];shots=_pair(st,'shots')[side]
 evidence=sum((xg>=.25,xgot>=.18,sot>=1,ibox>=2,touch>=5,big>=1,shots>=4));available=any(v>0 for v in (xg,xgot,sot,ibox,touch,big,shots))
 return {'xg':xg,'xgot':xgot,'sot':sot,'ibox':ibox,'touch':touch,'big':big,'shots':shots,'evidence':evidence,'available':available}

def _team_goals_needed(row,m):
 current=int(m.home_score if _side(row)==0 else m.away_score)
 try:line=float(row.get('line'))
 except:return 1
 return max(0,int(math.floor(line))+1-current)

def _match_goals_needed(row,m):
 current=int(m.home_score or 0)+int(m.away_score or 0)
 try:line=float(row.get('line'))
 except:return 1
 return max(0,int(math.floor(line))+1-current)

def _team_evidence(row,m,p):
 ev=_side_live_evidence(_stats(p),_side(row));ev['needed']=_team_goals_needed(row,m);return ev

def _team_allowed(row,m,p):
 ev=_team_evidence(row,m,p)
 if ev['needed']<=0:return False,'ALREADY_SETTLED',ev
 if not ev['available']:return False,'NO_TEAM_STATS',ev
 minimum=3 if ev['needed']>=2 else 2
 if ev['evidence']<minimum:return False,'LOW_TEAM_EVIDENCE',ev
 return True,'OK',ev

def _team_conf(row,m,p):
 ev=_team_evidence(row,m,p);side=_side(row);st=_stats(p);threat=0.;weight=0.
 for k,w in (('xg',30),('xgot',20),('shots_on_target',8),('shots_inside_box',3),('touches_box',.7),('big_chances',12)):
  a,b=_pair(st,k);vals=(a,b);threat+=vals[side]*w;weight+=max(vals)*w
 share=.5 if weight<=0 else max(.15,min(.85,threat/weight));market=_implied(row.get('odd'));pressure=float(getattr(p,'score',0) or 0)
 penalty=max(0,ev['needed']-1)*20
 return max(5.,min(88.,market*.38+pressure*.24+share*28+ev['evidence']*2-penalty))

def _btts_context(m,p):
 hs=int(m.home_score or 0);as_=int(m.away_score or 0)
 if hs>0 and as_>0:return False,'ALREADY_SETTLED',None
 if hs==0 and as_==0:
  h=_side_live_evidence(_stats(p),0);a=_side_live_evidence(_stats(p),1)
  if not h['available'] or not a['available']:return False,'NO_BTTS_TEAM_STATS',None
  if h['evidence']<2 or a['evidence']<2:return False,'LOW_BTTS_TEAM_EVIDENCE',None
  return True,'OK',None
 missing=0 if hs==0 else 1;ev=_side_live_evidence(_stats(p),missing)
 if not ev['available']:return False,'NO_BTTS_TEAM_STATS',ev
 if ev['evidence']<2:return False,'LOW_BTTS_TEAM_EVIDENCE',ev
 return True,'OK',ev

def _total_allowed(row,m,p):
 needed=_match_goals_needed(row,m);st=_stats(p);available=any(sum(_pair(st,k))>0 for k in ('xg','xgot','shots','shots_on_target','shots_inside_box','touches_box','big_chances'))
 # A total needing 2+ future goals must have actual LIVE attacking evidence.
 if needed<=0:return False,'ALREADY_SETTLED',needed
 if needed>=2 and not available:return False,'NO_TOTAL_STATS',needed
 return True,'OK',needed

def _total_conf(row,m,p):
 imp=_implied(row.get('odd'));pressure=float(getattr(p,'score',0) or 0);mom=float(getattr(p,'momentum',0) or 0);needed=_match_goals_needed(row,m);st=_stats(p)
 xg=sum(_pair(st,'xg'));xgot=sum(_pair(st,'xgot'));sot=sum(_pair(st,'shots_on_target'));shots=sum(_pair(st,'shots'));big=sum(_pair(st,'big_chances'))
 live_bonus=min(16.,xg*5+xgot*3+sot*1.2+shots*.25+big*2)
 # Each additional required future goal materially reduces settlement probability.
 penalty=max(0,needed-1)*18
 return max(5.,min(90.,imp*.42+pressure*.30+mom*.10+live_bonus-penalty))

def _model_conf(row,m,p):
 kind=str(row.get('market_type') or 'TOTAL')
 if kind.startswith('TEAM_TOTAL'):return _team_conf(row,m,p)
 if kind=='TOTAL':return _total_conf(row,m,p)
 try:odd=float(row['odd'])
 except:return float(getattr(p,'score',0) or 0)*.65
 if kind=='BTTS':
  market=_implied(odd);pressure=float(getattr(p,'score',0) or 0);mom=float(getattr(p,'momentum',0) or 0);hs=int(m.home_score or 0);as_=int(m.away_score or 0)
  if (hs>0) ^ (as_>0):
   missing=0 if hs==0 else 1;ev=_side_live_evidence(_stats(p),missing);bonus=min(12.,ev['xg']*8+ev['sot']*2+ev['shots']*.5);return max(5.,min(88.,market*.42+pressure*.28+mom*.15+bonus))
  return max(5.,min(84.,market*.45+pressure*.30+mom*.15))
 return float(row.get('confidence') if row.get('confidence') is not None else getattr(p,'score',0)*.65)

def _rank(r,m,p):
 try:odd=float(r['odd'])
 except:return -999.,{}
 kind=str(r.get('market_type') or 'TOTAL')
 if kind.startswith('TEAM_TOTAL'):
  allowed,why,ev=_team_allowed(r,m,p);r['team_market_gate']=why;r['team_goals_needed']=ev['needed'];r['team_evidence']=ev['evidence']
  if not allowed:return -999.,{'selector_reject':why,'team_goals_needed':ev['needed'],'team_evidence':ev['evidence']}
 elif kind=='BTTS':
  allowed,why,ev=_btts_context(m,p);r['btts_market_gate']=why
  if not allowed:return -999.,{'selector_reject':why,'btts_evidence':ev.get('evidence') if ev else None}
 elif kind=='TOTAL':
  allowed,why,needed=_total_allowed(r,m,p);r['match_goals_needed']=needed;r['total_market_gate']=why
  if not allowed:return -999.,{'selector_reject':why,'match_goals_needed':needed}
 conf=_model_conf(r,m,p);imp=_implied(odd);edge=conf-imp;r['value_edge']=round(edge,1);sources=int(r.get('source_count') or r.get('bookmakers') or 1);movement=float(r.get('movement_score') or 0);score=conf*.58+max(-15.,min(20.,edge))*.65+_confirmation(r)+_price(odd)+min(6.,max(0,sources-1)*3)+movement
 if kind in {'BTTS','TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'} and sources<2:score-=5
 if kind=='BTTS' and int(m.minute or 0)>=75:score-=5
 if str(r.get('external_market_status') or r.get('market_status') or '') in {'CONFLICT','DISAGREE'}:score-=4
 return score,{'selector_score':round(score,1),'selector_confidence':round(conf,1),'selector_implied':round(imp,1),'selector_edge':round(edge,1),'selector_movement':round(movement,1),'team_goals_needed':r.get('team_goals_needed'),'team_evidence':r.get('team_evidence'),'match_goals_needed':r.get('match_goals_needed')}

def _identity(r):
 return (str(r.get('scope') or ''),str(r.get('market_type') or ''),str(r.get('team_side') or ''),str(r.get('team_name') or ''),str(r.get('selection') or ''),str(r.get('line') or ''))

def _market(entries,m,p):
 recs,market=_orig_market(entries,m,p);market_movement.annotate(recs)
 for r in recs:r.pop('best_concrete_bet',None)
 ranked=[]
 for r in recs:
  if r.get('scope')!='FULL_TIME' or r.get('odd') is None:continue
  kind=str(r.get('market_type') or 'TOTAL')
  if kind not in {'TOTAL','BTTS','TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'} and r.get('goal_step') is None:continue
  score,meta=_rank(r,m,p);r.update(meta)
  if score>-900:ranked.append((score,r))
 ranked.sort(key=lambda x:x[0],reverse=True)
 # Deduplicate identical selections from different feeds: keep the best-ranked price.
 unique=[];seen=set()
 for score,r in ranked:
  key=_identity(r)
  if key in seen:continue
  seen.add(key);unique.append((score,r))
 if unique:
  best=unique[0][1];best['best_concrete_bet']=True
  keys=('scope','market_type','extra_market','team_side','team_name','line','selection','odd','source','source_prices','selector_score','selector_confidence','selector_implied','selector_edge','selector_movement','movement_status','movement_drop_pct','correlated_steam','market_status','team_goals_needed','team_evidence','match_goals_needed','btts_market_gate','total_market_gate')
  market['best_concrete_bet']={k:best.get(k) for k in keys};market['best_alternatives']=[{k:r.get(k) for k in keys} for _,r in unique[1:3]]
 else:
  market.pop('best_concrete_bet',None);market['best_alternatives']=[]
 return recs,market
lc._market=_market
