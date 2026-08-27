"""Auditable on-demand analytics for GOOL 2.0 LIVE history."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15
from report_now import _aux_state,_core_state,_market_label
from signal_journal import all_signals

MOSCOW=ZoneInfo("Europe/Moscow")


def _all_live_rows():return [r for r in all_signals() if r.get("kind")=="live"]
def _core_entries(rows):return [r for r in rows if str(r.get("reason") or "signal") in {"signal","reentry"} and str(r.get("engine") or "core") not in {FIRST_HALF_GOAL,SECOND_HALF_OVER15}]
def _num(r,*keys):
    for k in keys:
        v=r.get(k)
        if v is not None:
            try:return float(v)
            except Exception:pass
    return None

def _bucket_minute(m):
    m=int(m or 0)
    if m<=20:return "1–20'"
    if m<=40:return "21–40'"
    if m<=60:return "41–60'"
    if m<=74:return "61–74'"
    return "75+'"

def _bucket_rating(v):
    if v is None:return "нет данных"
    if v<75:return "<75 legacy"
    if v<80:return "75–79"
    if v<90:return "80–89"
    return "90+"

def _bucket_edge(v):
    if v is None:return "нет данных"
    if v<6:return "<6 pp"
    if v<10:return "6–9.9 pp"
    if v<15:return "10–14.9 pp"
    return "15+ pp"

def _market_type(r):
    p=r.get("primary") or {};kind=str(p.get("market_type") or p.get("market") or "TOTAL_OVER").upper()
    return {"TOTAL":"TOTAL OVER","OVER_UNDER":"TOTAL OVER","OVER":"TOTAL OVER","TOTAL_OVER":"TOTAL OVER","BTTS":"BTTS","TEAM_TOTAL_HOME":"TEAM TOTAL HOME","TEAM_TOTAL_AWAY":"TEAM TOTAL AWAY"}.get(kind,kind or "unknown")

def _settled(rows,state_fn):
    out=[]
    for r in rows:
        state,pnl=state_fn(r)
        if state=="pending":continue
        out.append((r,state,float(pnl or 0)))
    return out

def _groups(items,keyfn):
    d=defaultdict(lambda:[0,0,0.0])
    for r,state,pnl in items:
        k=keyfn(r);d[k][0]+=1;d[k][1]+=int(state=="win");d[k][2]+=pnl
    return d

def _fmt_groups(title,d,order=None):
    lines=[f"<b>{title}</b>"]
    for k in (order or list(d)):
        if k not in d:continue
        n,w,pnl=d[k];roi=pnl/n*100 if n else 0;lines.append(f"• {k}: <b>{w}/{n} · {round(w/n*100) if n else 0}%</b> · {pnl:+.2f}u · ROI {roi:+.1f}%")
    return lines

def _summary_line(label,items):
    n=len(items);w=sum(state=="win" for _,state,_ in items);l=sum(state=="loss" for _,state,_ in items);p=sum(state=="push" for _,state,_ in items);pnl=sum(x[2] for x in items);roi=pnl/n*100 if n else 0
    return f"• {label}: <b>{n}</b> · ✅ {w} · ❌ {l} · ↩️ {p} · <b>{pnl:+.2f}u</b> · ROI <b>{roi:+.1f}%</b>"

def _clv_lines(items):
    lines=[]
    for sec in (60,120):
        vals=[]
        for r,_,_ in items:
            try:v=float(r.get(f"clv_{sec}_implied_pp"))
            except (TypeError,ValueError):continue
            vals.append(v)
        if vals:
            avg=sum(vals)/len(vals);pos=sum(v>0 for v in vals)
            lines.append(f"• CLV {sec}s: <b>{avg:+.2f} pp</b> в среднем · положительный {pos}/{len(vals)}")
    return lines

def _next_goal_lines(rows):
    known=[]
    for r in rows:
        v=str(r.get("signal_result") or r.get("result") or "").strip().lower()
        if v in {"win","won","+"}:known.append(True)
        elif v in {"loss","lost","-"}:known.append(False)
    if not known:return []
    hits=sum(known);return [f"⚽ Next-goal diagnostic: <b>{hits}/{len(known)} · {round(hits/len(known)*100)}%</b>","<i>Это качество прогноза следующего гола, не ROI выбранного рынка.</i>"]

def _engine_section(title,rows):
    items=_settled(rows,_aux_state);lines=["",title]
    if not items:return lines+["• Пока нет закрытых входов."]
    lines.append(_summary_line("Итого",items))
    lines += [""]+_fmt_groups("По минуте входа",_groups(items,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
    ratings=_groups(items,lambda r:_bucket_rating(_num(r,"strategy_score","master")))
    if ratings:lines += [""]+_fmt_groups("По рейтингу стратегии",ratings,["<75 legacy","75–79","80–89","90+","нет данных"])
    return lines

def build_analysis_text():
    all_rows=_all_live_rows();core_all=_core_entries(all_rows)
    audited=[r for r in core_all if int(r.get("journal_version",0) or 0)>=4 and isinstance(r.get("primary"),dict)]
    legacy=len(core_all)-len(audited);core=_settled(audited,_core_state)
    lines=["🧠 <b>GOOL 2.0 — АНАЛИЗ ЗА ВСЁ ВРЕМЯ</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🟡 <b>GOOL CORE · AUDITABLE MARKET RESULTS</b>"]
    if core:
        lines.append(_summary_line("Итого",core))
        masters=[_num(r,"master") for r,_,_ in core];masters=[x for x in masters if x is not None]
        if masters:lines.append(f"⭐ Средний MASTER закрытых входов: <b>{sum(masters)/len(masters):.1f}/100</b>")
        lines += _next_goal_lines([r for r,_,_ in core])
        primary=[x for x in core if str(x[0].get("reason") or "signal")=="signal"];reentry=[x for x in core if str(x[0].get("reason") or "signal")=="reentry"]
        lines += ["","♻️ <b>Первичный vs re-entry</b>",_summary_line("Первичные",primary),_summary_line("После гола",reentry)]
        lines += [""]+_fmt_groups("⏱ По минуте входа",_groups(core,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
        lines += [""]+_fmt_groups("⭐ По MASTER",_groups(core,lambda r:_bucket_rating(_num(r,"master"))),["<75 legacy","75–79","80–89","90+","нет данных"])
        lines += [""]+_fmt_groups("🎯 По выбранному рынку",_groups(core,_market_type))
        edges=_groups(core,lambda r:_bucket_edge(_num(r.get("primary") or {},"selector_edge","value_edge")))
        if edges:lines += [""]+_fmt_groups("📐 По value edge",edges,["<6 pp","6–9.9 pp","10–14.9 pp","15+ pp","нет данных"])
        clv=_clv_lines(core)
        if clv:lines += ["","📉 <b>CLV после входа</b>"]+clv
        lines += ["","<b>Последние рассчитанные CORE:</b>"]
        for r,state,pnl in core[-8:]:
            mark="✅" if state=="win" else "❌" if state=="loss" else "↩️"
            lines.append(f"{mark} {r.get('home')} — {r.get('away')} | {_market_label(r)} · {pnl:+.2f}u")
    else:lines += ["Пока недостаточно закрытых auditable CORE-входов."]
    if legacy:lines += ["",f"ℹ️ Legacy CORE без сохранённого primary: <b>{legacy}</b> — не смешиваются с ROI GOOL 2.0."]
    fh=[r for r in all_rows if str(r.get("engine") or "")==FIRST_HALF_GOAL];sh=[r for r in all_rows if str(r.get("engine") or "")==SECOND_HALF_OVER15]
    lines += _engine_section("🔵 <b>ГОЛ В 1-М ТАЙМЕ · СИГНАЛ 15–25'</b>",fh)
    lines += _engine_section("🟣 <b>ТБ1.5 ВО 2-М ТАЙМЕ · РЕШЕНИЕ В ПЕРЕРЫВЕ</b>",sh)
    lines += ["","<i>Win/ROI CORE считаются только по сохранённой конкретной ставке. Next-goal diagnostic показан отдельно и не подменяет результат рынка.</i>"]
    return "\n".join(lines)
