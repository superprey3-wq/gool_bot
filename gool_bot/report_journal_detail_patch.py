"""Compact on-demand GOOL report with auditable results and BEST BET status."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import report_now
from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15

log=logging.getLogger('report_journal_detail_patch')
_WIN={'win','won','+'};_LOSS={'loss','lost','-'};_PUSH={'push','void','return','возврат'}

def _norm(v): return str(v or '').strip().lower()

def _mark(v):
    n=_norm(v)
    return '✅' if n in _WIN else '❌' if n in _LOSS else '↩️' if n in _PUSH else '⏳'

def _goal_state(r):
    s=_norm(r.get('signal_result'))
    if s in _WIN:return 'win'
    if s in _LOSS:return 'loss'
    return 'pending'

def _aux_state(r):
    s=_norm(r.get('result'))
    if s in _WIN:return 'win'
    if s in _LOSS:return 'loss'
    if s in _PUSH:return 'push'
    return 'pending'

def _counts(rows,state_fn):
    states=[state_fn(r) for r in rows]
    return (sum(s=='win' for s in states),sum(s=='loss' for s in states),sum(s=='push' for s in states),sum(s=='pending' for s in states))

def _line(r,label,state):
    score0=str(r.get('score_at_signal') or '—')
    score1=str(r.get('next_goal_score') or r.get('final_score') or '—')
    return f"{_mark(state)} {r.get('home')} — {r.get('away')} | {label} {r.get('minute')}' · {score0}→{score1}"

def _best_lines(rows):
    bb=[r for r in rows if r.get('kind')=='best_bet']
    w,l,p,wait=_counts(bb,_aux_state)
    lines=[f"🏆 <b>BEST BET:</b> {len(bb)} · ✅ {w} · ❌ {l} · ⏳ {wait}"]
    if bb:
        r=bb[-1];p0=r.get('primary') or {};name=p0.get('label') or p0.get('market') or p0.get('market_type') or 'рынок';odd=p0.get('odd');od=f" @{float(odd):.2f}" if odd else ''
        lines.append(f"Последняя: {_mark(r.get('result'))} {r.get('home')} — {r.get('away')} | {name}{od}")
    else:
        try:
            p=Path('best_bet_status.json')
            if p.exists():
                d=json.loads(p.read_text(encoding='utf-8'));reason=d.get('reason')
                if reason:lines.append(f"Фильтр: <b>{reason}</b>")
        except Exception:pass
    return lines

def build_report_text():
    rows=report_now._today_rows();core=report_now._live_signal_rows(rows);fh=report_now._engine_rows(rows,FIRST_HALF_GOAL);sh=report_now._engine_rows(rows,SECOND_HALF_OVER15)
    cw,cl,_,cp=_counts(core,_goal_state);fw,fl,fp,fwait=_counts(fh,_aux_state);sw,sl,sp,swait=_counts(sh,_aux_state)
    initial=sum(1 for r in core if str(r.get('reason') or 'signal')=='signal');reentries=sum(1 for r in core if str(r.get('reason') or 'signal')=='reentry')
    from datetime import datetime
    lines=[
        '📊 <b>GOOL 2.0 — СЕЙЧАС</b>',
        f"🗓 {datetime.now(report_now.MOSCOW).strftime('%d.%m.%Y %H:%M')}",
        '',
        f"🟡 <b>CORE:</b> {len(core)} входов ({initial}+{reentries}) · ✅ {cw} · ❌ {cl} · ⏳ {cp}",
        f"🔵 <b>1H GOAL:</b> {len(fh)} · ✅ {fw} · ❌ {fl} · ↩️ {fp} · ⏳ {fwait}",
        f"🟣 <b>2H ТБ1.5:</b> {len(sh)} · ✅ {sw} · ❌ {sl} · ↩️ {sp} · ⏳ {swait}",
    ]
    lines += _best_lines(rows)

    settled=[]
    for r in core:
        st=_goal_state(r)
        if st!='pending':settled.append((int(r.get('created_ts',0) or 0),r,'CORE',st))
    for r in fh:
        st=_aux_state(r)
        if st!='pending':settled.append((int(r.get('created_ts',0) or 0),r,'1H',st))
    for r in sh:
        st=_aux_state(r)
        if st!='pending':settled.append((int(r.get('created_ts',0) or 0),r,'2H',st))
    settled.sort(key=lambda x:x[0])
    if settled:
        lines += ['', '<b>Последние результаты:</b>']
        lines += [_line(r,label,st) for _,r,label,st in settled[-6:]]
    lines += ['', '<i>Полный JSON-журнал: команда /journal</i>']
    return '\n'.join(lines)

report_now.build_report_text=build_report_text
log.info('REPORT_JOURNAL_DETAIL compact enabled')
