"""Monkey PROGRUZ market-flow intelligence. Pure Python + SQLite, no paid API.
V10: de-vig trajectory, velocity/acceleration, persistence, reversal, source sync,
lead/lag, source agreement and main-total line migration.
"""
from __future__ import annotations
import json,math,sqlite3,statistics,time
from collections import defaultdict
from pathlib import Path
try: from proguz_fair_probability import fair_consensus
except Exception: fair_consensus=None

def _side(r):
 s=str(r.get('side') or r.get('selection') or '').upper();return 'OVER' if s in {'OVER','O','ТБ','TB'} else 'UNDER' if s in {'UNDER','U','ТМ','TM'} else ''
def _scope(r):
 s=str(r.get('scope') or 'FULL_TIME').upper().replace('-','_').replace(' ','_');return {'FULLTIME':'FULL_TIME','FT':'FULL_TIME','1H':'FIRST_HALF','2H':'SECOND_HALF'}.get(s,s)
def _source(r):
 b=str(r.get('bookmaker') or r.get('bookmaker_id') or '');src=str(r.get('source') or '').upper()
 if '1XBET' in b.upper() or 'BETB2B' in src:return '1xBet'
 if 'KAMBI' in b.upper() or 'KAMBI' in src:return 'Kambi/BetRivers'
 return b or src or 'unknown'
def _f(v,d=None):
 try:return float(v)
 except (TypeError,ValueError):return d
def _median(xs,d=0.0):
 a=[]
 for x in xs:
  try:
   v=float(x)
   if math.isfinite(v):a.append(v)
  except Exception:pass
 return statistics.median(a) if a else d

def _history(db_path,eid,scope,lookback):
 if not Path(db_path).exists():return []
 c=None
 try:
  c=sqlite3.connect(db_path,timeout=5);cut=time.time()-float(lookback)
  rows=c.execute("SELECT o.snapshot_id,s.ts,o.payload FROM odds o JOIN snapshots s ON s.id=o.snapshot_id WHERE s.complete=1 AND s.ts>=? AND o.event_id=? AND o.market IN ('TOTAL','OVER_UNDER') AND o.scope=? ORDER BY s.ts,o.id",(cut,str(eid),str(scope))).fetchall();out=[]
  for sid,ts,p in rows:
   try:r=json.loads(p)
   except Exception:continue
   if isinstance(r,dict):out.append((int(sid),float(ts),r))
  return out
 except Exception:return []
 finally:
  if c:
   try:c.close()
   except Exception:pass

def _paired(rows,line,side):
 g=defaultdict(dict)
 for sid,ts,r in rows:
  ln=_f(r.get('line'));sd=_side(r);odd=_f(r.get('odd'))
  if ln is None or abs(ln-float(line))>1e-6 or sd not in {'OVER','UNDER'} or odd is None or odd<=1.01:continue
  g[(sid,_source(r))][sd]=(odd,ts)
 out=defaultdict(list);key='over' if side=='OVER' else 'under'
 for (sid,src),p in g.items():
  if not {'OVER','UNDER'}<=p.keys():continue
  fair=fair_consensus(p['OVER'][0],p['UNDER'][0]) if fair_consensus else {}
  if fair:out[src].append({'ts':max(p['OVER'][1],p['UNDER'][1]),'p':float(fair[key]),'vig':float(fair.get('vig',0)),'method_spread_pp':float(fair.get('method_spread_pp',0))})
 for src in out:out[src].sort(key=lambda x:x['ts'])
 return out

def _metrics(p):
 if len(p)<2:return None
 a,b=p[0],p[-1];mins=max((b['ts']-a['ts'])/60,1/60);move=(b['p']-a['p'])*100;vel=move/mins
 dif=[(p[i]['p']-p[i-1]['p'])*100 for i in range(1,len(p))];pers=sum(d>0.05 for d in dif)/len(dif) if dif else 0
 peak=p[0]['p'];dd=0
 for x in p[1:]:peak=max(peak,x['p']);dd=max(dd,(peak-x['p'])*100)
 rev=dd>=1.75 and move<dd;acc=0
 if len(p)>=3:
  m=len(p)//2;p0,pm,p1=p[0],p[m],p[-1];t1=max((pm['ts']-p0['ts'])/60,1/60);t2=max((p1['ts']-pm['ts'])/60,1/60);acc=((p1['p']-pm['p'])*100/t2)-((pm['p']-p0['p'])*100/t1)
 hit=next((x['ts'] for x in p[1:] if x['p']>=a['p']+.015),None)
 return {'move_pp':round(move,3),'velocity_pp_min':round(vel,3),'acceleration_pp_min2':round(acc,3),'persistence':round(pers,3),'reversal':bool(rev),'first_hit_ts':hit,'samples':len(p),'fair_start':round(a['p']*100,2),'fair_now':round(b['p']*100,2),'method_spread_pp':round(_median(x.get('method_spread_pp') for x in p),3)}

def _main_lines(rows):
 g=defaultdict(lambda:defaultdict(dict));tm={}
 for sid,ts,r in rows:
  ln=_f(r.get('line'));sd=_side(r);odd=_f(r.get('odd'))
  if ln is None or sd not in {'OVER','UNDER'} or odd is None or odd<=1.01:continue
  src=_source(r);g[(sid,src)][ln][sd]=odd;tm[(sid,src)]=ts
 out=defaultdict(list)
 for key,lines in g.items():
  choices=[]
  for ln,p in lines.items():
   if not {'OVER','UNDER'}<=p.keys():continue
   f=fair_consensus(p['OVER'],p['UNDER']) if fair_consensus else {}
   if f:choices.append((abs(float(f['over'])-.5),ln,float(f['over'])))
  if choices:
   _,ln,p=sorted(choices,key=lambda x:(x[0],x[1]))[0];out[key[1]].append({'ts':tm[key],'line':ln,'over_fair':p})
 for src in out:out[src].sort(key=lambda x:x['ts'])
 return out

def analyze(db_path,event_id,scope,line,side,lookback_seconds=900):
 side=str(side).upper();rows=_history(db_path,event_id,scope,lookback_seconds)
 if not rows:return {'available':False,'reason':'no_history'}
 series=_paired(rows,line,side);sm={}
 for src,p in series.items():
  m=_metrics(p)
  if m:sm[src]=m
 supportive={s:m for s,m in sm.items() if m['move_pp']>=.75 and not m['reversal']};hits=sorted((m['first_hit_ts'],s) for s,m in supportive.items() if m.get('first_hit_ts'))
 lead_source=hits[0][1] if hits else None;lead_ts=hits[0][0] if hits else None;lags={s:round(ts-lead_ts,1) for ts,s in hits} if lead_ts else {};sync=(hits[-1][0]-hits[0][0]) if len(hits)>=2 else None;sync_ok=sync is not None and sync<=180
 current=[m['fair_now'] for m in sm.values()];agreement_spread=(max(current)-min(current)) if len(current)>=2 else 0.0;agreement=max(0.0,min(1.0,1.0-agreement_spread/8.0)) if len(current)>=2 else 0.5
 main=_main_lines(rows);migs={};oriented=[]
 for src,p in main.items():
  if len(p)<2:continue
  d=float(p[-1]['line'])-float(p[0]['line']);support=d if side=='OVER' else -d;migs[src]={'from':p[0]['line'],'to':p[-1]['line'],'delta':round(d,3),'support':round(support,3)}
  if support>0:oriented.append(support)
 moves=[m['move_pp'] for m in supportive.values()];vel=[m['velocity_pp_min'] for m in supportive.values()];acc=[m['acceleration_pp_min2'] for m in supportive.values()];pers=[m['persistence'] for m in supportive.values()]
 fm=_median(moves);v=_median(vel);a=_median(acc);p=_median(pers);mig=_median(oriented);revs=sum(m['reversal'] for m in sm.values())
 score=36+min(22,max(0,fm)*3.2)+min(10,max(0,v)*2.2)+min(7,max(0,a)*1.5)+min(8,p*8)+min(8,mig*12)+(6 if sync_ok else 0)+agreement*5-min(15,revs*5);score=max(0,min(100,score))
 traj=[]
 for ts in sorted({x['ts'] for pts in series.values() for x in pts})[-8:]:
  vals=[]
  for pts in series.values():
   near=[x for x in pts if abs(x['ts']-ts)<=2]
   if near:vals.append(near[-1]['p']*100)
  if vals:traj.append({'ts':round(ts,1),'fair_pct':round(_median(vals),2)})
 return {'available':bool(sm),'lookback_s':int(lookback_seconds),'fair_sources':len(supportive),'paired_sources':len(sm),'fair_move_pp':round(fm,3),'velocity_pp_min':round(v,3),'acceleration_pp_min2':round(a,3),'persistence':round(p,3),'reversal_sources':revs,'sync_seconds':None if sync is None else round(sync,1),'sync_confirmed':sync_ok,'lead_source':lead_source,'lead_lag_seconds':lags,'source_agreement':round(agreement,3),'source_spread_pp':round(agreement_spread,3),'line_migration':round(mig,3),'line_migration_sources':len(oriented),'flow_score':round(score,1),'source_metrics':sm,'line_migrations':migs,'trajectory':traj}
