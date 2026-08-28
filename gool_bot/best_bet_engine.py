"""Unified GOOL BEST BET: fair value + flow + context + persistent one-bet gate."""
from __future__ import annotations
import logging,os,time,requests
import live_candidate_patch as lc,market_movement,telegram_subscribers,unified_bot
from best_bet_card import render_entry,render_result
from best_bet_calibration import penalty_for
from fair_value import model_probability,two_way_fair,expected_value
from live_engine import fetch_stats,parse_stats,calculate_goal_pressure
from runtime_resource_guard import allow_optional
from signal_journal import add_signal,all_signals,update_signal
log=logging.getLogger('best_bet_engine');MIN_SCORE=float(os.getenv('BEST_BET_MIN_SCORE','82'));MIN_EDGE=float(os.getenv('BEST_BET_MIN_EDGE_PP','4'));MIN_ODD=float(os.getenv('BEST_BET_MIN_ODD','1.25'));MAX_ODD=float(os.getenv('BEST_BET_MAX_ODD','4.50'));COOLDOWN=int(os.getenv('BEST_BET_COOLDOWN_MINUTES','12'))*60;SETTLE_AFTER=int(os.getenv('BEST_BET_SETTLE_AFTER_SECONDS','600'));MIN_SETTLE_MINUTE=int(os.getenv('BEST_BET_MIN_SETTLE_LAST_MINUTE','80'));_ACTIVE={}
def _f(v,d=0.):
 try:return float(v)
 except Exception:return d
def _side(r):
 k=str(r.get('market_type') or r.get('market') or '').upper();s=str(r.get('selection') or '').upper()
 if k in {'TOTAL_UNDER','UNDER'} or s in {'UNDER','U'}:return 'UNDER'
 if k in {'TOTAL','TOTAL_OVER','OVER_UNDER','OVER'} or s in {'OVER','O'}:return 'OVER'
 if k=='BTTS':return 'NO' if s in {'NO','N'} else 'YES'
 return s or k
def _name(r):
 k=str(r.get('market_type') or r.get('market') or 'TOTAL').upper();s=_side(r);line=r.get('line')
 if 'TOTAL' in k and not k.startswith('TEAM'):return f"ТМ {float(line):g}" if s=='UNDER' else f"ТБ {float(line):g}"
 if k=='BTTS':return 'Обе забьют — НЕТ' if s=='NO' else 'Обе забьют — ДА'
 return str(r.get('label') or r.get('market') or r.get('selection') or k)
def _same_pair(a,b):
 ka=str(a.get('market_type') or a.get('market') or '').upper();kb=str(b.get('market_type') or b.get('market') or '').upper();ta='TOTAL' in ka and not ka.startswith('TEAM');tb='TOTAL' in kb and not kb.startswith('TEAM')
 if not (ka==kb or ta and tb):return False
 try:
  if abs(float(a.get('line'))-float(b.get('line')))>1e-9:return False
 except Exception:
  if a.get('line')!=b.get('line'):return False
 return {_side(a),_side(b)} in ({'OVER','UNDER'},{'YES','NO'})
def _rank(r,m,p):
 odd=_f(r.get('odd'))
 if odd<MIN_ODD or odd>MAX_ODD:return None
 selector=_f(r.get('selector_confidence'),_f(r.get('confidence'),_f(getattr(p,'score',0))));po=r.get('gool_model_prob');pp=float(po)*100 if po is not None else None;conf=selector if pp is None else selector*.68+pp*.32;mf=r.get('market_fair_prob');implied=float(mf)*100 if mf is not None else 100/odd;edge=conf-implied;ev=expected_value(conf/100,odd);move=_f(r.get('movement_score'));status=str(r.get('movement_status') or r.get('market_status') or '').upper();bonus={'CONFIRMED_MONEY_FLOW':10,'CONFIRMED_STEAM':7,'STEAM':4,'REVERSAL':-10,'DISAGREE':-12,'CONFLICT':-18}.get(status,0);context=min(100,max(0,_f(getattr(p,'score',0))*.65+_f(getattr(p,'momentum',0))*.35));cal,_=penalty_for(r);score=conf*.50+max(-15,min(20,edge))*.72+move*.45+bonus+context*.12+cal;suspicious=edge>28 or (ev is not None and ev>.55)
 if edge<MIN_EDGE:score-=8
 if suspicious:score-=18
 return {'score':round(max(0,min(100,score)),1),'confidence':round(conf,1),'edge':round(edge,1),'ev_pct':None if ev is None else round(ev*100,1),'market_score':round(move,1),'context':round(context,1),'status':status or 'PRIMARY','odd':odd,'name':_name(r),'row':r,'pair_confirmed':bool(r.get('pair_confirmed')),'suspicious':suspicious}
def _send(png,caption):
 if not unified_bot.BOT_TOKEN:return False
 sent=False
 for chat in telegram_subscribers.get_subscribers():
  try:sent=requests.post(f'https://api.telegram.org/bot{unified_bot.BOT_TOKEN}/sendPhoto',data={'chat_id':str(chat),'caption':caption},files={'photo':('gool-best-bet.png',png,'image/png')},timeout=25).ok or sent
  except requests.RequestException as e:log.warning('BEST_BET photo failed %s: %s',chat,e)
 return sent
def _pending(eid):return next((r for r in all_signals() if r.get('kind')=='best_bet' and str(r.get('event_id') or '')==str(eid) and str(r.get('result') or 'pending').lower() in {'','pending','wait','waiting'}),None)
def _record(m,b):
 r=b['row'];eid=str(m.event_id);minute=int(m.minute or 0);score=f'{int(m.home_score or 0)}:{int(m.away_score or 0)}';key=f"best_bet:{eid}:{minute}:{b['name']}";rec={'kind':'best_bet','event_id':eid,'home':m.home,'away':m.away,'minute':minute,'last_minute':minute,'score_at_signal':score,'last_score':score,'last_seen_ts':int(time.time()),'master':b['score'],'model_score':b['confidence'],'market_score':b['market_score'],'context_score':b['context'],'value_edge_pp':b['edge'],'ev_pct':b['ev_pct'],'market_status':b['status'],'primary':{'scope':r.get('scope') or 'FULL_TIME','market_type':r.get('market_type'),'market':r.get('market'),'selection':r.get('selection'),'line':r.get('line'),'odd':b['odd'],'label':b['name']},'stake_units':1.,'result':'pending','journal_version':10};return key if add_signal(rec,key) else None
def _settle(p,score):
 try:h,a=map(int,str(score).split(':',1))
 except Exception:return None
 k=str(p.get('market_type') or p.get('market') or '').upper();s=str(p.get('selection') or '').upper();line=p.get('line')
 if 'TOTAL' in k or k in {'OVER','UNDER','OVER_UNDER'}:
  if line is None:return None
  side='UNDER' if k in {'TOTAL_UNDER','UNDER'} or s in {'UNDER','U'} else 'OVER';total=h+a
  if abs(total-float(line))<1e-9:return 'push'
  return 'win' if (side=='OVER' and total>float(line)) or (side=='UNDER' and total<float(line)) else 'loss'
 if k=='BTTS':return 'win' if ((h>0 and a>0)==(s not in {'NO','N'})) else 'loss'
 return None
def update_results(live):
 now=int(time.time());by={str(m.event_id):m for m in live or []};sent=0
 for row in all_signals():
  if row.get('kind')!='best_bet' or str(row.get('result') or 'pending').lower()!='pending':continue
  key=str(row.get('dedupe_key') or '');m=by.get(str(row.get('event_id') or ''))
  if m:update_signal(key,last_score=f'{int(m.home_score or 0)}:{int(m.away_score or 0)}',last_minute=int(m.minute or 0),last_seen_ts=now);continue
  if now-int(row.get('last_seen_ts',0) or 0)<SETTLE_AFTER or int(row.get('last_minute',0) or 0)<MIN_SETTLE_MINUTE:continue
  result=_settle(row.get('primary') or {},row.get('last_score'))
  if not result:continue
  odd=_f((row.get('primary') or {}).get('odd'));pnl=round(odd-1,3) if result=='win' else -1. if result=='loss' else 0.
  try:delivered=_send(render_result(row,result,row.get('last_score'),pnl),'GOOL BEST BET • RESULT')
  except Exception:log.exception('BEST_BET result card failed');delivered=False
  update_signal(key,result=result,bet_pnl_units=pnl,final_score=row.get('last_score'),settled_ts=now,result_card_sent=delivered);sent+=int(delivered)
 return sent
def evaluate_match(m):
 eid=str(m.event_id);now=time.time()
 if _pending(eid) or (eid in _ACTIVE and now-_ACTIVE[eid]<COOLDOWN):return False
 try:body=fetch_stats(eid);stats=parse_stats(body) if body else {};p=calculate_goal_pressure(m,stats,None);entries=unified_bot._fetch_event_odds(eid);recs,_=lc._market(entries,m,p)
 except Exception as e:log.info('BEST_BET input unavailable %s %s',eid,e);return False
 market_movement.annotate(recs,event_id=eid,score=f'{m.home_score}:{m.away_score}',minute=m.minute)
 for r in recs:
  r['gool_model_prob']=model_probability(r,m,stats);opp=next((x for x in recs if x is not r and x.get('odd') and _same_pair(r,x)),None)
  if opp:r['market_fair_prob']=two_way_fair(r.get('odd'),opp.get('odd'))[0];r['pair_confirmed']=bool(r['market_fair_prob'])
 ranked=[x for r in recs if r.get('scope')=='FULL_TIME' and r.get('odd') is not None if (x:=_rank(r,m,p))];ranked.sort(key=lambda x:x['score'],reverse=True)
 if not ranked:return False
 b=ranked[0]
 if b['score']<MIN_SCORE or b['edge']<MIN_EDGE or b['status'] in {'CONFLICT','DISAGREE','REVERSAL'} or b['suspicious']:return False
 if not _record(m,b):return False
 sent=_send(render_entry(m,b,ranked[1:4]),f"🏆 GOOL BEST BET • {b['name']} @ {b['odd']:.2f}")
 if sent:_ACTIVE[eid]=now;log.info('BEST_BET_SENT %s %s score=%.1f edge=%.1f',eid,b['name'],b['score'],b['edge'])
 return sent
def scan(live):
 ok,res,reason=allow_optional()
 if not ok:log.warning('BEST_BET_SKIPPED_RESOURCE reason=%s rss=%s avail=%s',reason,res.get('rss_mb'),res.get('mem_available_mb'));return 0
 return sum(1 for m in live or [] if evaluate_match(m))
