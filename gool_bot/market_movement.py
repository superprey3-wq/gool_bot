"""Bounded multi-source money-flow scoring for GOOL."""
from __future__ import annotations
import time
_HISTORY={};_MAX_POINTS=8;_TTL=1800;_MAX_KEYS=400
def _f(v,d=0.):
 try:return float(v)
 except Exception:return d
def _dir(sp):
 mv=(sp or {}).get('movement') or {};return str(mv.get('direction') or 'flat'),_f(mv.get('drop_pct'))
def _src(sp,i):return str(sp.get('bookmaker') or sp.get('source') or sp.get('provider') or f'src{i}')
def _odd(sp):
 for k in ('odd','odds','price','last_odds','current_odds'):
  x=_f(sp.get(k),0)
  if x>1:return x
 return 0.
def _key(r,e):return f"{e}|{r.get('market_type') or r.get('market')}|{r.get('selection')}|{r.get('team_side')}|{r.get('line')}"
def _remember(r,e,score,minute):
 k=_key(r,e);now=time.time();h=_HISTORY.get(k)
 if h and ((score is not None and h.get('score') is not None and str(score)!=str(h.get('score'))) or (minute is not None and h.get('minute') is not None and int(minute)<int(h.get('minute')))):h=None;_HISTORY.pop(k,None)
 if h is None:
  if len(_HISTORY)>=_MAX_KEYS:
   oldest=min(_HISTORY,key=lambda x:((_HISTORY[x].get('points') or [(0,{})])[-1][0]));_HISTORY.pop(oldest,None)
  h=_HISTORY.setdefault(k,{'points':[]})
 snap={_src(sp,i):_odd(sp) for i,sp in enumerate(r.get('source_prices') or []) if _odd(sp)>1};h['score']=score;h['minute']=minute;h['points'].append((now,snap));h['points']=h['points'][-_MAX_POINTS:];return h
def score_row(row,event_id=None,score=None,minute=None):
 prices=row.get('source_prices') or [];toward=against=0;drops=[]
 for sp in prices:
  d,p=_dir(sp);drops.append(p);toward+=int(d=='toward' and p>=.5);against+=int(d=='against' and p<=-.5)
 n=len(prices);strong=max(drops) if drops else 0.;h=_remember(row,event_id,score,minute);pts=h['points'];breadth=toward/max(1,n)*100 if n else 0.;velocity=persistence=reversal=0.
 if len(pts)>=2:
  t0,s0=pts[0];t1,s1=pts[-1];dt=max(1,t1-t0);moves=[(o0-s1[src])/o0*100 for src,o0 in s0.items() if src in s1 and o0>1 and s1[src]>1]
  if moves:velocity=max(-100,min(100,sum(moves)/len(moves)*60/dt*10));persistence=sum(x>=.5 for x in moves)/max(1,n)*100
  for src,o1 in s1.items():
   hist=[s.get(src) for _,s in pts[:-1] if s.get(src)]
   if hist and o1>min(hist)*1.015:reversal+=1
 reversal=reversal/max(1,n)*100 if n else 0.
 if n>=3 and toward>=3:status='CONFIRMED_MONEY_FLOW';base=8.
 elif n>=2 and toward>=2:status='CONFIRMED_STEAM';base=6.
 elif toward:status='STEAM';base=2.
 elif against>toward:status='REVERSAL';base=-4.
 else:status='STABLE';base=0.
 points=base+min(5,max(0,strong)*.55)+min(4,breadth*.04)+min(3,max(0,velocity)*.03)+min(3,persistence*.03)-min(8,reversal*.08)
 if against>toward:points=min(points,-3.)
 return {'movement_status':status,'movement_score':round(max(-12,min(20,points)),1),'movement_sources':n,'movement_toward':toward,'movement_against':against,'movement_drop_pct':round(strong,2),'flow_breadth':round(breadth,1),'flow_velocity':round(velocity,1),'flow_persistence':round(persistence,1),'flow_reversal':round(reversal,1)}
def annotate(rows,event_id=None,score=None,minute=None):
 now=time.time()
 for k in list(_HISTORY):
  p=_HISTORY[k].get('points') or []
  if not p or now-p[-1][0]>_TTL:_HISTORY.pop(k,None)
 for r in rows:r.update(score_row(r,event_id,score,minute))
 goalish=[r for r in rows if str(r.get('market_type') or 'TOTAL') in {'TOTAL','BTTS','TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'} and r.get('movement_status') in {'STEAM','CONFIRMED_STEAM','CONFIRMED_MONEY_FLOW'}]
 if len({str(r.get('market_type') or 'TOTAL') for r in goalish})>=2:
  for r in goalish:r['correlated_steam']=True;r['movement_score']=round(min(22,_f(r.get('movement_score'))+3),1)
 return rows
