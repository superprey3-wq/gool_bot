"""On-demand analytics for GOOL LIVE history."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from signal_journal import all_signals
from report_now import _current_live_ids
from live_engine import fetch_summary
from daily_report import _score_from_summary
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15
MOSCOW=ZoneInfo("Europe/Moscow")
def _all_live_rows():return [r for r in all_signals() if r.get("kind")=="live"]
def _entries(rows):return [r for r in rows if str(r.get("reason") or "signal") in {"signal","reentry"}]
def _num(r,*keys):
    for k in keys:
        v=r.get(k)
        if v is not None:
            try:return float(v)
            except:pass
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
    if v<70:return "60–69"
    if v<80:return "70–79"
    if v<90:return "80–89"
    return "90+"
def _has_goal_confirmation(entry,all_rows):
    eid=str(entry.get("event_id") or "");ts=int(entry.get("created_ts",0) or 0);later=sorted(int(r.get("created_ts",0) or 0) for r in all_rows if str(r.get("event_id") or "")==eid and str(r.get("reason") or "signal") in {"signal","reentry"} and int(r.get("created_ts",0) or 0)>ts);cutoff=later[0] if later else 10**18
    return any(str(r.get("event_id") or "")==eid and str(r.get("reason") or "")=="goal" and ts<=int(r.get("created_ts",0) or 0)<cutoff for r in all_rows)
def _settled(entries,all_rows):
    live_ids=_current_live_ids();cache={};out=[]
    for r in entries:
        eid=str(r.get("event_id") or "");stored=str(r.get("result") or "pending").lower()
        if stored in {"+","win","won"}:out.append((r,True,str(r.get("final_score") or "✓")));continue
        if stored in {"-","loss","lost"}:out.append((r,False,str(r.get("final_score") or "—")));continue
        if _has_goal_confirmation(r,all_rows):out.append((r,True,"подтверждённый гол"));continue
        if live_ids is not None and eid in live_ids:continue
        if eid not in cache:
            try:cache[eid]=fetch_summary(eid)
            except:cache[eid]=None
        body=cache[eid]
        if not body:continue
        try:fh,fa,_,_=_score_from_summary(body);sh,sa=map(int,str(r.get("score_at_signal","0:0")).split(":"))
        except:continue
        if fh<sh or fa<sa or fh+fa<sh+sa:continue
        out.append((r,(fh+fa)>(sh+sa),f"{fh}:{fa}"))
    return out
def _engine_items(rows,engine):
    out=[]
    for r in rows:
        if str(r.get("engine") or "").strip().lower()!=engine:continue
        result=str(r.get("result") or "pending").strip().lower()
        if result in {"+","win","won"}:out.append((r,True,str(r.get("final_score") or "✓")))
        elif result in {"-","loss","lost"}:out.append((r,False,str(r.get("final_score") or "—")))
    return out
def _groups(items,keyfn):
    d=defaultdict(lambda:[0,0])
    for r,win,_ in items:k=keyfn(r);d[k][0]+=1;d[k][1]+=int(win)
    return d
def _fmt_groups(title,d,order=None):
    lines=[f"<b>{title}</b>"]
    for k in (order or list(d)):
        if k not in d:continue
        n,w=d[k];lines.append(f"• {k}: <b>{w}/{n} · {round(w/n*100) if n else 0}%</b>")
    return lines
def _summary_line(label,items):
    n=len(items);w=sum(int(win) for _,win,_ in items);return f"• {label}: <b>{n}</b> закрыто · ✅ {w} · ❌ {n-w} · <b>{round(w/n*100) if n else 0}%</b>"
def _engine_section(title,items):
    lines=["",title]
    if not items:return lines+["• Пока нет закрытых входов."]
    n=len(items);w=sum(int(win) for _,win,_ in items);lines.append(f"Закрытых входов: <b>{n}</b> · ✅ {w} · ❌ {n-w} · <b>{round(w/n*100)}%</b>")
    lines += [""]+_fmt_groups("По минуте входа",_groups(items,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
    ratings=_groups(items,lambda r:_bucket_rating(_num(r,"strategy_score","master")))
    if ratings:lines += [""]+_fmt_groups("По рейтингу стратегии",ratings,["60–69","70–79","80–89","90+","нет данных"])
    return lines
def build_analysis_text():
    all_rows=_all_live_rows();core=_settled(_entries(all_rows),all_rows);wins=sum(int(w) for _,w,_ in core)
    lines=["🧠 <b>GOOL — АНАЛИЗ ЗА ВСЁ ВРЕМЯ</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🟡 <b>GOOL CORE</b>",f"Закрытых входов: <b>{len(core)}</b> · ✅ {wins} · ❌ {len(core)-wins}"]
    if core:
        primary=[x for x in core if str(x[0].get("reason") or "signal")=="signal"];reentry=[x for x in core if str(x[0].get("reason") or "signal")=="reentry"]
        lines += ["","♻️ <b>Первичный vs повторный вход</b>",_summary_line("Первичные",primary),_summary_line("После гола",reentry)]
        lines += [""]+_fmt_groups("⏱ По минуте входа",_groups(core,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
        lines += [""]+_fmt_groups("⭐ По MASTER",_groups(core,lambda r:_bucket_rating(_num(r,"master"))),["60–69","70–79","80–89","90+","нет данных"])
    else:lines += ["","Пока недостаточно закрытых CORE-входов."]
    fh=_engine_items(all_rows,FIRST_HALF_GOAL);sh=_engine_items(all_rows,SECOND_HALF_OVER15)
    lines += _engine_section("🔵 <b>ГОЛ В 1-М ТАЙМЕ · СИГНАЛ 15–25'</b>",fh)
    lines += _engine_section("🟣 <b>ТБ1.5 ВО 2-М ТАЙМЕ · РЕШЕНИЕ В ПЕРЕРЫВЕ</b>",sh)
    lines += ["","<i>CORE и две дополнительные стратегии считаются отдельно по своим рынкам и результатам.</i>"]
    return "\n".join(lines)
