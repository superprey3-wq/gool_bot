"""On-demand analytics for the full GOOL LIVE signal history."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from signal_journal import all_signals
from report_now import _current_live_ids
from live_engine import fetch_summary
from daily_report import _score_from_summary
from multi_engine import HT_HUNTER,LATE_RISK
MOSCOW=ZoneInfo("Europe/Moscow")

def _all_live_rows():
    return [r for r in all_signals() if r.get("kind")=="live"]

def _entries(rows):return [r for r in rows if str(r.get("reason") or "signal") in {"signal","reentry"}]
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
def _has_goal_confirmation(entry,all_rows):
    """Legacy runtime truth: a goal journal row after this entry and before next entry proves WIN."""
    eid=str(entry.get("event_id") or "");ts=int(entry.get("created_ts",0) or 0)
    later_entries=sorted(int(r.get("created_ts",0) or 0) for r in all_rows if str(r.get("event_id") or "")==eid and str(r.get("reason") or "signal") in {"signal","reentry"} and int(r.get("created_ts",0) or 0)>ts)
    cutoff=later_entries[0] if later_entries else 10**18
    return any(str(r.get("event_id") or "")==eid and str(r.get("reason") or "")=="goal" and ts<=int(r.get("created_ts",0) or 0)<cutoff for r in all_rows)
def _settled(entries,all_rows):
    live_ids=_current_live_ids();cache={};out=[]
    for r in entries:
        eid=str(r.get("event_id") or "");stored=str(r.get("result") or "pending").lower()
        if stored in {"+","win","won"}:
            out.append((r,True,str(r.get("final_score") or "✓")));continue
        if stored in {"-","loss","lost"}:
            out.append((r,False,str(r.get("final_score") or "—")));continue
        if _has_goal_confirmation(r,all_rows):
            out.append((r,True,"подтверждённый гол"));continue
        if live_ids is not None and eid in live_ids:continue
        if eid not in cache:
            try:cache[eid]=fetch_summary(eid)
            except Exception:cache[eid]=None
        body=cache[eid]
        if not body:continue
        try:fh,fa,_,_=_score_from_summary(body);sh,sa=map(int,str(r.get("score_at_signal","0:0")).split(":"))
        except Exception:continue
        if fh<sh or fa<sa:continue
        if fh+fa<sh+sa:continue
        out.append((r,(fh+fa)>(sh+sa),f"{fh}:{fa}"))
    return out

def _engine_items(all_rows,engine):
    """Risk engines settle themselves in runtime; only confirmed +/- rows count here."""
    out=[]
    for r in all_rows:
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
    n=len(items);w=sum(int(win) for _,win,_ in items);l=n-w
    return f"• {label}: <b>{n}</b> закрыто · ✅ {w} · ❌ {l} · <b>{round(w/n*100) if n else 0}%</b>"

def _engine_section(title,items):
    lines=["",title]
    if not items:
        return lines+["• Пока нет закрытых входов."]
    n=len(items);w=sum(int(win) for _,win,_ in items);l=n-w
    lines.append(f"Закрытых входов: <b>{n}</b> · ✅ {w} · ❌ {l} · <b>{round(w/n*100)}%</b>")
    mins=_groups(items,lambda r:_bucket_minute(r.get("minute")))
    lines += [""]+_fmt_groups("По минуте входа",mins,["1–20'","21–40'","41–60'","61–74'","75+'"]) 
    risk=_groups(items,lambda r:_bucket_rating(_num(r,"risk_score","master")))
    if risk:
        lines += [""]+_fmt_groups("По рейтингу стратегии",risk,["60–69","70–79","80–89","90+","нет данных"])
    losses=[x for x in items if not x[1]]
    if losses:
        lines += ["","❌ <b>Последние незашедшие:</b>"]
        for r,_,score in losses[-5:]:
            rating=_num(r,"risk_score","master");rt=f" · SCORE {rating:.0f}" if rating is not None else ""
            lines.append(f"• {r.get('home')} — {r.get('away')} | {r.get('minute')}' {r.get('score_at_signal')} → {score}{rt}")
    return lines

def build_analysis_text()->str:
    all_rows=_all_live_rows();rows=_entries(all_rows);items=_settled(rows,all_rows);wins=sum(int(w) for _,w,_ in items);losses=len(items)-wins
    lines=["🧠 <b>GOOL — АНАЛИЗ ЗА ВСЁ ВРЕМЯ</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🟡 <b>GOOL CORE</b>",f"Закрытых входов за всю историю: <b>{len(items)}</b> · ✅ {wins} · ❌ {losses}"]
    if items:
        primary=[x for x in items if str(x[0].get("reason") or "signal")=="signal"]
        reentry=[x for x in items if str(x[0].get("reason") or "signal")=="reentry"]
        lines += ["","♻️ <b>Первичный vs повторный вход</b>",_summary_line("Первичные",primary),_summary_line("После гола",reentry)]
        lines += [""]+_fmt_groups("⏱ По минуте входа",_groups(items,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
        lines += [""]+_fmt_groups("⭐ По MASTER-рейтингу",_groups(items,lambda r:_bucket_rating(_num(r,"master"))),["60–69","70–79","80–89","90+","нет данных"])
        lines += [""]+_fmt_groups("⚽ По счёту/результативности на входе",_groups(items,lambda r:(lambda g:"0–1 гол" if g<=1 else "2–3 гола" if g<=3 else "4+ гола")(sum(map(int,str(r.get("score_at_signal","0:0")).split(":"))))),["0–1 гол","2–3 гола","4+ гола"])
        if reentry:
            lines += [""]+_fmt_groups("♻️ Повторные — по минуте",_groups(reentry,lambda r:_bucket_minute(r.get("minute"))),["1–20'","21–40'","41–60'","61–74'","75+'"]) 
            lines += [""]+_fmt_groups("♻️ Повторные — по MASTER",_groups(reentry,lambda r:_bucket_rating(_num(r,"master"))),["60–69","70–79","80–89","90+","нет данных"])
        candidates=[]
        for label,d in [("минута",_groups(items,lambda r:_bucket_minute(r.get("minute")))),("MASTER",_groups(items,lambda r:_bucket_rating(_num(r,"master"))))]:
            for k,(n,w) in d.items():
                if n>=3 and k!="нет данных":candidates.append((w/n*100,n,label,k))
        if reentry:
            for label,d in [("повторный вход, минута",_groups(reentry,lambda r:_bucket_minute(r.get("minute")))),("повторный вход, MASTER",_groups(reentry,lambda r:_bucket_rating(_num(r,"master"))))]:
                for k,(n,w) in d.items():
                    if n>=3 and k!="нет данных":candidates.append((w/n*100,n,label,k))
        lines += ["","🔎 <b>Что проверить в первую очередь</b>"]
        if candidates:
            for rate,n,label,k in sorted(candidates)[:4]:lines.append(f"• {label} {k}: {round(rate)}% на {n} закрытых входах")
        else:lines.append("• Пока выборка по группам слишком маленькая — пороги лучше не менять.")
        if losses:
            lines += ["","❌ <b>Последние незашедшие:</b>"]
            for r,_,score in [x for x in items if not x[1]][-8:]:
                rating=_num(r,"master");rt=f" · MASTER {rating:.0f}" if rating is not None else "";tag="♻️ " if str(r.get("reason") or "signal")=="reentry" else ""
                lines.append(f"• {tag}{r.get('home')} — {r.get('away')} | {r.get('minute')}' {r.get('score_at_signal')} → {score}{rt}")
    else:
        lines += ["","Пока недостаточно закрытых CORE-входов для анализа."]

    ht_items=_engine_items(all_rows,HT_HUNTER)
    late_items=_engine_items(all_rows,LATE_RISK)
    lines += _engine_section("🔵 <b>HT HUNTER · ПЕРВЫЙ ТАЙМ</b>",ht_items)
    lines += _engine_section("🔴 <b>LATE RISK · ВТОРОЙ ТАЙМ</b>",late_items)
    lines += ["","<i>CORE, HT HUNTER и LATE RISK считаются отдельно. CORE использует подтверждённый LIVE-гол/финальный summary; рискованные стратегии — только подтверждённый runtime result.</i>"]
    return "\n".join(lines)
