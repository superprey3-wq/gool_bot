"""On-demand analytics for today's GOOL LIVE entries."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from signal_journal import all_signals
from report_now import _current_live_ids
from live_engine import fetch_summary
from daily_report import _score_from_summary
MOSCOW=ZoneInfo("Europe/Moscow")

def _today_entries():
    today=datetime.now(MOSCOW).date().isoformat();out=[]
    for r in all_signals():
        if r.get("kind")!="live" or str(r.get("reason") or "signal") not in {"signal","reentry"}:continue
        try:d=datetime.fromtimestamp(int(r.get("created_ts",0)),MOSCOW).date().isoformat()
        except Exception:continue
        if d==today:out.append(r)
    return out

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
    if v<70:return "60–69"
    if v<80:return "70–79"
    if v<90:return "80–89"
    return "90+"

def _settled(rows):
    live_ids=_current_live_ids();cache={};out=[]
    for r in rows:
        eid=str(r.get("event_id") or "")
        if live_ids is not None and eid in live_ids:continue
        if eid not in cache:
            try:cache[eid]=fetch_summary(eid)
            except Exception:cache[eid]=None
        body=cache[eid]
        if not body:continue
        try:fh,fa,_,_=_score_from_summary(body);sh,sa=map(int,str(r.get("score_at_signal","0:0")).split(":"))
        except Exception:continue
        if fh+fa<sh+sa:continue
        out.append((r,(fh+fa)>(sh+sa),f"{fh}:{fa}"))
    return out

def _groups(items,keyfn):
    d=defaultdict(lambda:[0,0])
    for r,win,_ in items:
        k=keyfn(r);d[k][0]+=1;d[k][1]+=int(win)
    return d

def _fmt_groups(title,d,order=None):
    lines=[f"<b>{title}</b>"]
    keys=order or list(d)
    for k in keys:
        if k not in d:continue
        n,w=d[k];rate=round(w/n*100) if n else 0
        lines.append(f"• {k}: <b>{w}/{n} · {rate}%</b>")
    return lines

def build_analysis_text()->str:
    rows=_today_entries();items=_settled(rows);wins=sum(int(w) for _,w,_ in items);losses=len(items)-wins
    lines=["🧠 <b>GOOL — АНАЛИЗ СИГНАЛОВ</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","",f"Закрытых входов: <b>{len(items)}</b> · ✅ {wins} · ❌ {losses}"]
    if not items:return "\n".join(lines+["","Пока недостаточно закрытых входов для анализа."])
    lines += [""]+_fmt_groups("⏱ По минуте входа",_groups(items,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
    lines += [""]+_fmt_groups("⭐ По рейтингу",_groups(items,lambda r:_bucket_rating(_num(r,"master","rating","score"))),["60–69","70–79","80–89","90+","нет данных"])
    lines += [""]+_fmt_groups("⚽ По счёту/результативности на входе",_groups(items,lambda r:(lambda g:"0–1 гол" if g<=1 else "2–3 гола" if g<=3 else "4+ гола")(sum(map(int,str(r.get("score_at_signal","0:0")).split(":"))))),["0–1 гол","2–3 гола","4+ гола"])
    # Identify weak slices only with a minimally useful sample; do not auto-change model.
    candidates=[]
    for label,d in [("минута",_groups(items,lambda r:_bucket_minute(r.get("minute")))),("рейтинг",_groups(items,lambda r:_bucket_rating(_num(r,"master","rating","score"))))]:
        for k,(n,w) in d.items():
            if n>=3:
                rate=w/n*100
                candidates.append((rate,n,label,k))
    weak=sorted(candidates)[:3]
    lines += ["","🔎 <b>Что проверить в первую очередь</b>"]
    if weak:
        for rate,n,label,k in weak:lines.append(f"• {label} {k}: {round(rate)}% на {n} закрытых входах")
    else:lines.append("• Пока выборка по отдельным группам слишком маленькая — пороги лучше не менять.")
    if losses:
        lines += ["","❌ <b>Последние незашедшие:</b>"]
        for r,_,score in [x for x in items if not x[1]][-8:]:
            rating=_num(r,"master","rating","score");rt=f" · рейтинг {rating:.0f}" if rating is not None else ""
            lines.append(f"• {r.get('home')} — {r.get('away')} | {r.get('minute')}' {r.get('score_at_signal')} → {score}{rt}")
    lines += ["","<i>Это диагностика, а не автоматическая смена порогов. Чем больше закрытых входов, тем надёжнее выводы.</i>"]
    return "\n".join(lines)
