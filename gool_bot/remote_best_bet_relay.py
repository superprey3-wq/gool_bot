"""Relay approved BEST BET signals from MonkeyBytes to the main Telegram bot."""
from __future__ import annotations
import json,logging,os,threading,time
from pathlib import Path
from types import SimpleNamespace
import requests
import unified_bot
from best_bet_card import render_entry
from telegram_subscribers import get_subscribers

log=logging.getLogger('remote_best_bet_relay')
URL=os.getenv('GOOL_REMOTE_BEST_BET_URL','http://eu.monkey-network.xyz:5056/bestbet')
POLL=max(15,int(os.getenv('GOOL_REMOTE_BEST_BET_RELAY_POLL','20')))
MAX_AGE=max(120,int(os.getenv('GOOL_REMOTE_BEST_BET_MAX_AGE','900')))
STATE=Path(os.getenv('GOOL_REMOTE_BEST_BET_SENT','remote_best_bet_sent.json'))

def _load():
 try:
  d=json.loads(STATE.read_text(encoding='utf-8'));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _save(d):
 cutoff=time.time()-3*86400;d={k:v for k,v in d.items() if float(v or 0)>=cutoff};tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(d),encoding='utf-8');tmp.replace(STATE)
def _key(row):
 return str(row.get('dedupe_key') or f"{row.get('event_id')}:{row.get('minute')}:{(row.get('primary') or {}).get('label')}:{row.get('created_ts') or row.get('last_seen_ts')}")
def _best(row):
 p=row.get('primary') or {}
 return {'name':str(p.get('label') or p.get('market') or 'BEST BET'),'odd':float(p.get('odd') or row.get('odd') or 0),'score':float(row.get('master') or row.get('strategy_score') or 0),'confidence':float(row.get('model_score') or row.get('confidence') or 0),'edge':float(row.get('value_edge_pp') or 0),'market_score':float(row.get('market_score') or 0),'status':str(row.get('market_status') or 'PRIMARY'),'history_score':float(row.get('history_score') or 0),'context':float(row.get('context_score') or 0),'row':p}
def _match(row):
 score=str(row.get('score_at_signal') or '0:0')
 try:h,a=map(int,score.split(':',1))
 except Exception:h,a=0,0
 return SimpleNamespace(home=str(row.get('home') or '?'),away=str(row.get('away') or '?'),minute=int(row.get('minute') or 0),home_score=h,away_score=a)
def _send(row):
 token=unified_bot.BOT_TOKEN
 if not token:return 0
 best=_best(row);m=_match(row)
 try:png=render_entry(m,best,[])
 except Exception as exc:log.exception('REMOTE_BEST_BET card failed: %s',exc);png=None
 caption=f"🏆 GOOL BEST BET • {best['name']} @ {best['odd']:.2f} • {best['score']:.0f}/100"
 n=0
 for cid in get_subscribers():
  try:
   if png:r=requests.post(f'https://api.telegram.org/bot{token}/sendPhoto',data={'chat_id':str(cid),'caption':caption},files={'photo':('gool-best-bet.png',png,'image/png')},timeout=25)
   else:r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':str(cid),'text':caption},timeout=15)
   n+=int(r.ok)
  except requests.RequestException:pass
 return n

def poll_once():
 try:
  r=requests.get(URL,timeout=8);r.raise_for_status();payload=r.json() or {};row=payload.get('signal')
 except Exception as exc:log.warning('REMOTE_BEST_BET_OFFLINE %s',exc);return 0
 if not isinstance(row,dict):return 0
 ts=int(row.get('created_ts') or row.get('last_seen_ts') or payload.get('worker_ts') or 0)
 if ts and time.time()-ts>MAX_AGE:return 0
 key=_key(row);sent=_load()
 if not key or key in sent:return 0
 delivered=_send(row)
 if delivered:
  sent[key]=time.time();_save(sent);log.info('REMOTE_BEST_BET_SENT event=%s market=%s score=%s delivered=%d',row.get('event_id'),(row.get('primary') or {}).get('label'),row.get('master'),delivered);return 1
 return 0

def loop():
 log.info('REMOTE BEST BET relay active url=%s poll=%ss',URL,POLL)
 while True:
  poll_once();time.sleep(POLL)
threading.Thread(target=loop,name='remote-best-bet-relay',daemon=True).start()
