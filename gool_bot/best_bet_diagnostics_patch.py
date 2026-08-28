"""Expose why BEST BET did or did not fire without changing selection thresholds."""
from __future__ import annotations
import json,logging,time
from pathlib import Path
import best_bet_engine as bbe

log=logging.getLogger('best_bet_diagnostics_patch')
STATUS=Path('best_bet_status.json')
_orig_rank=bbe._rank
_orig_scan=bbe.scan
_stats={}

def _reset():
    _stats.clear();_stats.update(total_rank_calls=0,eligible=0,top=None)

def _rank(row,m,p):
    x=_orig_rank(row,m,p);_stats['total_rank_calls']=_stats.get('total_rank_calls',0)+1
    if x:
        _stats['eligible']=_stats.get('eligible',0)+1
        t=_stats.get('top')
        if t is None or float(x.get('score') or 0)>float(t.get('score') or 0):
            _stats['top']={k:x.get(k) for k in ('name','score','edge','status','suspicious','odd','confidence','market_score','context')}
    return x

def _write(payload):
    try:
        tmp=STATUS.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATUS)
    except Exception as exc:log.warning('BEST_BET_DIAG_WRITE failed: %s',exc)

def _reason(sent,live):
    if sent:return 'SENT'
    top=_stats.get('top')
    if not live:return 'NO_LIVE_MATCHES'
    if _stats.get('total_rank_calls',0)==0:return 'NO_MARKET_RECOMMENDATIONS'
    if not top:return 'NO_ELIGIBLE_ODDS'
    if bool(top.get('suspicious')):return 'SUSPICIOUS_VALUE'
    if str(top.get('status') or '').upper() in {'CONFLICT','DISAGREE','REVERSAL'}:return f"MARKET_{str(top.get('status')).upper()}"
    if float(top.get('edge') or -999)<float(bbe.MIN_EDGE):return 'EDGE_BELOW_MIN'
    if float(top.get('score') or 0)<float(bbe.MIN_SCORE):return 'SCORE_BELOW_MIN'
    return 'BLOCKED_AFTER_RANK'

def scan(live):
    _reset();started=time.time();sent=_orig_scan(live);reason=_reason(sent,live or [])
    payload={'ts':int(time.time()),'live':len(live or []),'sent':int(sent),'reason':reason,'min_score':bbe.MIN_SCORE,'min_edge_pp':bbe.MIN_EDGE,'min_odd':bbe.MIN_ODD,'max_odd':bbe.MAX_ODD,'rank_calls':_stats.get('total_rank_calls',0),'eligible':_stats.get('eligible',0),'top':_stats.get('top'),'elapsed_ms':int((time.time()-started)*1000)}
    _write(payload)
    top=payload.get('top') or {}
    log.info('BEST_BET_SCAN live=%d sent=%d reason=%s rank=%d eligible=%d top=%s score=%s edge=%s status=%s',payload['live'],payload['sent'],reason,payload['rank_calls'],payload['eligible'],top.get('name'),top.get('score'),top.get('edge'),top.get('status'))
    return sent

bbe._rank=_rank
bbe.scan=scan
log.info('BEST_BET_DIAGNOSTICS enabled min_score=%.1f min_edge=%.1f',bbe.MIN_SCORE,bbe.MIN_EDGE)
