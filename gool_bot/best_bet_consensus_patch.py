"""Prevent BEST BET from contradicting active GOOL specialist engines."""
import time,best_bet_engine as bbe
from signal_journal import all_signals
_CACHE=(0.,{})
def _active():
 global _CACHE
 now=time.time()
 if now-_CACHE[0]<20:return _CACHE[1]
 d={}
 for r in all_signals():
  if str(r.get('result') or 'pending').lower()!='pending':continue
  eng=str(r.get('engine') or '')
  if eng not in {'FIRST_HALF_GOAL','SECOND_HALF_OVER15'}:continue
  try:score=float(r.get('strategy_score') or 0)
  except Exception:score=0
  if score>=75:d[str(r.get('event_id') or '')]=max(d.get(str(r.get('event_id') or ''),0),2 if eng=='SECOND_HALF_OVER15' else 1)
 _CACHE=(now,d);return d

def _orig(row,m,p,hist=None):
 try:return bbe._ORIGINAL_RANK(row,m,p,hist)
 except TypeError:return bbe._ORIGINAL_RANK(row,m,p)

def rank(row,m,p,hist=None):
 x=_orig(row,m,p,hist);need=_active().get(str(getattr(m,'event_id','') or ''),0)
 if x and need and bbe._side(row)=='UNDER':
  try:conflict=int(getattr(m,'home_score',0) or 0)+int(getattr(m,'away_score',0) or 0)+need>=float(row.get('line'))
  except Exception:conflict=False
  if conflict:x['score']=0.;x['status']='CONFLICT';x['specialist_conflict']=True
 return x
bbe._ORIGINAL_RANK=bbe._rank
bbe._rank=rank
