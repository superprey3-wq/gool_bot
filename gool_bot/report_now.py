"""Build auditable on-demand snapshots of today's GOOL 2.0 signal journal."""
from __future__ import annotations
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from live_engine import discover_live_matches
from market_settlement import settle_primary
from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15
from signal_journal import all_signals

MOSCOW=ZoneInfo("Europe/Moscow")
_PENDING={"","pending","wait","waiting"}
_WIN={"+","win","won"}
_LOSS={"-","loss","lost"}
_PUSH={"push","void","return","возврат"}


def _today_rows():
    today=datetime.now(MOSCOW).date().isoformat();rows=[]
    for row in all_signals():
        try:created=datetime.fromtimestamp(int(row.get("created_ts",0)),MOSCOW)
        except Exception:continue
        if created.date().isoformat()==today:rows.append(row)
    return rows


def _live_signal_rows(rows):
    aux={FIRST_HALF_GOAL,SECOND_HALF_OVER15}
    return [r for r in rows if r.get("kind")=="live" and str(r.get("reason") or "signal") in {"signal","reentry"} and str(r.get("engine") or "core") not in aux]


def _engine_rows(rows,engine):
    return [r for r in rows if r.get("kind")=="live" and str(r.get("engine") or "")==engine]


def _is_pending_entry(row):
    return str(row.get("result") or "pending").strip().lower() in _PENDING


def _current_live_ids():
    try:matches=asyncio.run(discover_live_matches())
    except Exception:return None
    return {str(m.event_id) for m in matches}


def build_live_signals_text()->str:
    rows=[r for r in _today_rows() if r.get("kind")=="live" and _is_pending_entry(r)];live_ids=_current_live_ids()
    if live_ids is None:return "⚠️ Не удалось получить LIVE-список Flashscore. Попробуй ещё раз через минуту."
    active=[r for r in rows if str(r.get("event_id","")) in live_ids and str(r.get("reason") or "") in {"signal","reentry",FIRST_HALF_GOAL,SECOND_HALF_OVER15}]
    latest={}
    for r in active:
        key=f"{r.get('engine') or 'core'}:{r.get('event_id')}";old=latest.get(key)
        if old is None or int(r.get("created_ts",0) or 0)>int(old.get("created_ts",0) or 0):latest[key]=r
    active=sorted(latest.values(),key=lambda r:int(r.get("created_ts",0) or 0),reverse=True)
    if not active:return "🟢 <b>В ИГРЕ</b>\n\nСейчас незакрытых LIVE-входов нет."
    lines=[f"🟢 <b>В ИГРЕ — {len(active)}</b>","<i>Только реально открытые GOOL 2.0 позиции.</i>",""]
    for r in active[:20]:
        try:when=datetime.fromtimestamp(int(r.get("created_ts",0)),MOSCOW).strftime("%H:%M")
        except Exception:when="—"
        engine=str(r.get("engine") or "core")
        label="CORE" if engine in {"","core"} else "1H GOAL" if engine==FIRST_HALF_GOAL else "2H O1.5"
        lines.append(f"⏳ <b>{r.get('home')} — {r.get('away')}</b>\n↳ {label} · вход {r.get('minute')}' · {r.get('score_at_signal')} · {when}")
    if len(active)>20:lines.append(f"\n…и ещё {len(active)-20}")
    return "\n".join(lines)


def _row_pnl(row):
    try:return float(row.get("pnl_units"))
    except (TypeError,ValueError):pass
    result=str(row.get("result") or "").strip().lower()
    try:odd=float(row.get("odd") or (row.get("primary") or {}).get("odd") or 0)
    except (TypeError,ValueError):odd=0.0
    if result in _WIN and odd>1:return odd-1.0
    if result in _LOSS:return -1.0
    if result in _PUSH:return 0.0
    return None


def _core_state(row):
    result=str(row.get("result") or "pending").strip().lower()
    if result in _WIN:return "win",_row_pnl(row)
    if result in _LOSS:return "loss",_row_pnl(row)
    if result in _PUSH:return "push",0.0
    final=row.get("final_score");primary=row.get("primary")
    if final and isinstance(primary,dict):
        settlement=settle_primary(primary,final)
        if settlement:
            r=str(settlement.get("result") or "").lower();p=float(settlement.get("pnl_units",0) or 0)
            if r in _WIN:return "win",p
            if r in _LOSS:return "loss",p
            if r in _PUSH:return "push",p
    return "pending",None


def _aux_state(row):
    result=str(row.get("result") or "pending").strip().lower()
    if result in _WIN:return "win",_row_pnl(row)
    if result in _LOSS:return "loss",_row_pnl(row)
    if result in _PUSH:return "push",0.0
    return "pending",None


def _market_label(row):
    p=row.get("primary") or {};kind=str(p.get("market_type") or p.get("market") or "").upper();line=p.get("line")
    if kind=="BTTS":return "ОЗ — Да"
    if kind=="TEAM_TOTAL_HOME":return f"ИТБ хозяев {line:g}" if isinstance(line,(int,float)) else "ИТБ хозяев"
    if kind=="TEAM_TOTAL_AWAY":return f"ИТБ гостей {line:g}" if isinstance(line,(int,float)) else "ИТБ гостей"
    if line is not None:
        try:return f"ТБ {float(line):g}"
        except Exception:pass
    return kind or "рынок"


def _metrics(rows,state_fn):
    states=[(r,*state_fn(r)) for r in rows];settled=[x for x in states if x[1]!="pending"]
    wins=sum(x[1]=="win" for x in settled);losses=sum(x[1]=="loss" for x in settled);pushes=sum(x[1]=="push" for x in settled);pending=len(states)-len(settled)
    pnl=sum(float(x[2] or 0) for x in settled);roi=(pnl/len(settled)*100) if settled else 0.0
    odds=[]
    for r,_,_ in settled:
        try:o=float(r.get("odd") or (r.get("primary") or {}).get("odd") or 0)
        except Exception:continue
        if o>1:odds.append(o)
    return {"states":states,"settled":len(settled),"wins":wins,"losses":losses,"pushes":pushes,"pending":pending,"pnl":pnl,"roi":roi,"avg_odd":sum(odds)/len(odds) if odds else None}


def _summary_lines(title,rows,state_fn):
    m=_metrics(rows,state_fn);lines=["",title,f"Входов: <b>{len(rows)}</b> · закрыто: <b>{m['settled']}</b> · ⏳ {m['pending']}",f"✅ {m['wins']} · ❌ {m['losses']} · ↩️ {m['pushes']}"]
    if m["settled"]:
        hit=round(m["wins"]/max(1,m["wins"]+m["losses"])*100) if m["wins"]+m["losses"] else 0
        lines.append(f"🎯 Win rate без возвратов: <b>{hit}%</b>")
        lines.append(f"📈 PnL: <b>{m['pnl']:+.2f}u</b> · ROI: <b>{m['roi']:+.1f}%</b>")
    if m["avg_odd"]:lines.append(f"💰 Средний LIVE-кэф: <b>{m['avg_odd']:.2f}</b>")
    return lines,m


def _core_quality_lines(rows):
    masters=[];goal_known=[]
    for r in rows:
        try:
            v=float(r.get("master"))
            masters.append(v)
        except (TypeError,ValueError):pass
        s=str(r.get("signal_result") or "").strip().lower()
        if s in {"win","won","+"}:goal_known.append(True)
        elif s in {"loss","lost","-"}:goal_known.append(False)
    lines=[]
    if masters:
        lines.append(f"⭐ Средний MASTER: <b>{sum(masters)/len(masters):.1f}/100</b> · 80+: <b>{sum(x>=80 for x in masters)}/{len(masters)}</b>")
    if goal_known:
        hits=sum(goal_known);lines.append(f"⚽ Next-goal diagnostic: <b>{hits}/{len(goal_known)} · {round(hits/len(goal_known)*100)}%</b>")
        lines.append("<i>Next-goal — диагностика прогноза, не результат конкретной ставки.</i>")
    return lines


def build_report_text()->str:
    rows=_today_rows();core_rows=_live_signal_rows(rows);fh_rows=_engine_rows(rows,FIRST_HALF_GOAL);sh_rows=_engine_rows(rows,SECOND_HALF_OVER15)
    initial=sum(1 for r in core_rows if str(r.get("reason") or "signal")=="signal");reentries=sum(1 for r in core_rows if str(r.get("reason") or "signal")=="reentry")
    lines=["📊 <b>GOOL 2.0 — УМНЫЙ ОТЧЁТ НА СЕЙЧАС</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🟡 <b>GOOL CORE · РЕАЛЬНЫЙ РЫНОК</b>",f"Первичных: <b>{initial}</b> · re-entry: <b>{reentries}</b>"]
    core_lines,core_m=_summary_lines("",core_rows,_core_state);lines+=core_lines[1:];lines+=_core_quality_lines(core_rows)
    if core_rows:
        lines.append("<b>Последние CORE-входы:</b>")
        for r,state,pnl in core_m["states"][-8:]:
            mark="✅" if state=="win" else "❌" if state=="loss" else "↩️" if state=="push" else "⏳"
            odd=(r.get("primary") or {}).get("odd") or r.get("odd");odd_txt=f" @{float(odd):.2f}" if odd else ""
            master=r.get("master");master_txt=f" · M{float(master):.0f}" if master is not None else ""
            lines.append(f"{mark} {r.get('home')} — {r.get('away')} | {r.get('minute')}' · {_market_label(r)}{odd_txt}{master_txt}"+(f" · {float(pnl):+.2f}u" if pnl is not None else ""))
    fh_lines,_=_summary_lines("🔵 <b>1-Й ТАЙМ · ГОЛ 15–25'</b>",fh_rows,_aux_state);lines+=fh_lines
    sh_lines,_=_summary_lines("🟣 <b>2-Й ТАЙМ · ТБ1.5 В ПЕРЕРЫВЕ</b>",sh_rows,_aux_state);lines+=sh_lines
    if not rows:lines += ["","Сегодня в журнале пока нет сигналов."]
    lines += ["","<i>CORE ROI считается только по сохранённой конкретной ставке. Сила сигнала и факт следующего гола показаны отдельно, чтобы не завышать результативность.</i>"]
    return "\n".join(lines)
