"""Append GOOL V3 FT/1H/2H concrete-total performance to /report and /analysis."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from signal_journal import all_signals
import report_now,signal_analysis

_orig_report=report_now.build_report_text
_orig_analysis=signal_analysis.build_analysis_text
TZ=ZoneInfo("Europe/Moscow")

def _rows(period=None,today=False):
    xs=[r for r in all_signals() if r.get("engine")=="GOAL_DISTRIBUTION_V3"]
    if today:
        d=datetime.now(TZ).date();xs=[r for r in xs if datetime.fromtimestamp(int(r.get("created_ts",0) or 0),TZ).date()==d]
    return [r for r in xs if r.get("period")==period] if period else xs

def _state(r):
    s=str(r.get("result") or "pending").lower()
    try:o=float(r.get("odd") or 0)
    except:o=0
    if s=="win":return s,(max(0.0,o-1.0) if o>1 else None)
    if s=="loss":return s,(-1.0 if o>1 else None)
    if s=="push":return s,(0.0 if o>1 else None)
    return "pending",None

def _market(r):
    side="ТБ" if str(r.get("side"))=="OVER" else "ТМ";line=r.get("line")
    try:return f"{side} {float(line):g}"
    except:return side

def _summary(period,today=False):
    rows=_rows(period,today=today);settled=[(r,*_state(r)) for r in rows if _state(r)[0]!="pending"]
    w=sum(s=="win" for _,s,_ in settled);l=sum(s=="loss" for _,s,_ in settled);p=sum(s=="push" for _,s,_ in settled)
    priced=[x for x in settled if x[2] is not None];pnl=sum(x[2] for x in priced);roi=pnl/len(priced)*100 if priced else 0
    label={"FULL_TIME":"🟡 FULL MATCH","FIRST_HALF":"🔵 FIRST HALF","SECOND_HALF":"🟣 SECOND HALF"}[period]
    model_only=sum(not bool(r.get("odd")) for r in rows)
    lines=[f"{label}: <b>{len(rows)}</b> входов · ✅ {w} · ❌ {l} · ↩️ {p} · ⏳ {len(rows)-len(settled)}"]
    if model_only:lines.append(f"↳ MODEL ONLY без кэфа: <b>{model_only}</b>")
    if priced:lines.append(f"↳ priced PnL <b>{pnl:+.2f}u</b> · ROI <b>{roi:+.1f}%</b>")
    if rows:
        odds=[float(r.get("odd")) for r in rows if r.get("odd")];probs=[float(r.get("model_probability")) for r in rows if r.get("model_probability") is not None];vals=[float(r.get("value_edge")) for r in rows if r.get("value_edge") is not None]
        if probs:lines.append(f"↳ avg model {sum(probs)/len(probs):.1f}%"+(f" · avg odds {sum(odds)/len(odds):.2f}" if odds else "")+(f" · value +{sum(vals)/len(vals):.1f}pp" if vals else ""))
    return lines

def build_report_text():
    base=_orig_report();lines=[base,"","🎯 <b>GOOL V3 · СЕГОДНЯ · КОНКРЕТНЫЕ ТОТАЛЫ</b>"]
    for p in ("FULL_TIME","FIRST_HALF","SECOND_HALF"):lines+=_summary(p,today=True)
    last=sorted(_rows(today=True),key=lambda r:int(r.get("created_ts",0) or 0))[-6:]
    if last:
        lines+=["","<b>Последние V3:</b>"]
        for r in last:
            s,pnl=_state(r);mark="✅" if s=="win" else "❌" if s=="loss" else "↩️" if s=="push" else "⏳";price=f" @{float(r.get('odd')):.2f}" if r.get("odd") else " · MODEL"
            tail=f" · {pnl:+.2f}u" if pnl is not None else ""
            lines.append(f"{mark} {r.get('period')} · {r.get('home')} — {r.get('away')} · {_market(r)}{price} · model {float(r.get('model_probability')):.1f}%{tail}")
    return "\n".join(lines)

def build_analysis_text():
    base=_orig_analysis();rows=_rows();settled=[r for r in rows if _state(r)[0]!="pending"]
    lines=[base,"","🧠 <b>V3 TOTAL ANALYSIS · ALL TIME</b>"]
    for p in ("FULL_TIME","FIRST_HALF","SECOND_HALF"):lines+=_summary(p)
    if settled:
        groups=defaultdict(lambda:[0,0])
        for r in settled:
            s,_=_state(r);k=f"{r.get('period')} / {'OVER' if r.get('side')=='OVER' else 'UNDER'}";groups[k][0]+=1;groups[k][1]+=int(s=="win")
        lines+=["","<b>OVER / UNDER:</b>"]
        for k,(n,w) in sorted(groups.items()):lines.append(f"• {k}: {w}/{n}")
        priced=[r for r in settled if r.get("value_edge") is not None]
        hi=[_state(r)[0] for r in priced if float(r.get("value_edge",0) or 0)>=8];lo=[_state(r)[0] for r in priced if float(r.get("value_edge",0) or 0)<8]
        if hi:lines.append(f"• Value 8pp+: {sum(s=='win' for s in hi)}/{len(hi)}")
        if lo:lines.append(f"• Value <8pp: {sum(s=='win' for s in lo)}/{len(lo)}")
    return "\n".join(lines)

report_now.build_report_text=build_report_text
signal_analysis.build_analysis_text=build_analysis_text
