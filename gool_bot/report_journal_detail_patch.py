"""Restore human-readable result details in the on-demand GOOL report."""
from __future__ import annotations
import json
import logging
from pathlib import Path
import report_now
from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15

log=logging.getLogger('report_journal_detail_patch')
_orig=report_now.build_report_text
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

def _line(r,label):
    st=_goal_state(r) if label=='CORE' else _norm(r.get('result'))
    score0=str(r.get('score_at_signal') or '—')
    score1=str(r.get('next_goal_score') or r.get('final_score') or '—')
    return f"{_mark(st)} {r.get('home')} — {r.get('away')} | {label} · {r.get('minute')}' · {score0} → {score1}"

def _best_status(rows):
    bb=[r for r in rows if r.get('kind')=='best_bet']
    won=sum(_norm(r.get('result')) in _WIN for r in bb);lost=sum(_norm(r.get('result')) in _LOSS for r in bb);pending=sum(_norm(r.get('result') or 'pending') not in _WIN|_LOSS|_PUSH for r in bb)
    lines=['','🏆 <b>ЛУЧШАЯ СТАВКА</b>',f"Отправлено: <b>{len(bb)}</b> · ✅ {won} · ❌ {lost} · ⏳ {pending}"]
    if not bb:
        lines.append('Пока ни один матч не прошёл все фильтры BEST BET.')
    for r in bb[-4:]:
        p=r.get('primary') or {};odd=p.get('odd');name=p.get('label') or p.get('market') or p.get('market_type') or 'рынок'
        odds=f" @{float(odd):.2f}" if odd else ''
        lines.append(f"{_mark(r.get('result'))} {r.get('home')} — {r.get('away')} | {name}{odds} · M{float(r.get('master') or 0):.0f}")
    try:
        p=Path('best_bet_status.json')
        if p.exists():
            d=json.loads(p.read_text(encoding='utf-8'));reason=d.get('reason');top=d.get('top') or {}
            if reason:lines.append(f"Последний фильтр: <b>{reason}</b>")
            if top:lines.append(f"Лучший кандидат: {top.get('name','—')} · score {top.get('score','—')} · edge {top.get('edge','—')}pp")
    except Exception:pass
    return lines

def build_report_text():
    base=_orig()
    rows=report_now._today_rows();core=report_now._live_signal_rows(rows);fh=report_now._engine_rows(rows,FIRST_HALF_GOAL);sh=report_now._engine_rows(rows,SECOND_HALF_OVER15)
    known=[r for r in core if _goal_state(r)!='pending']
    cw=sum(_goal_state(r)=='win' for r in known);cl=sum(_goal_state(r)=='loss' for r in known)
    extra=['','📒 <b>ЖУРНАЛ РЕЗУЛЬТАТОВ</b>',f"CORE по факту следующего гола: ✅ <b>{cw}</b> · ❌ <b>{cl}</b> · ⏳ <b>{len(core)-len(known)}</b>"]
    if known:
        extra.append('<b>Последние рассчитанные CORE:</b>')
        extra += [_line(r,'CORE') for r in known[-8:]]
    if fh:
        extra.append("<b>1H GOAL — команды:</b>")
        extra += [_line(r,'1H') for r in fh[-8:]]
    if sh:
        extra.append("<b>2H ТБ1.5 — команды:</b>")
        extra += [_line(r,'2H') for r in sh[-8:]]
    extra += _best_status(rows)
    text=base+'\n'+'\n'.join(extra)
    if len(text)>3950:
        # Keep Telegram-safe while preserving the most useful result block.
        text='\n'.join(extra)
    return text

report_now.build_report_text=build_report_text
log.info('REPORT_JOURNAL_DETAIL enabled: team results + BEST BET status')
