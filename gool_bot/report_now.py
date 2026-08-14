"""Build on-demand snapshots of today's GOOL BOT signal journal."""
from __future__ import annotations
import asyncio,time
from datetime import datetime
from zoneinfo import ZoneInfo
from live_engine import discover_live_matches, fetch_summary
from daily_report import _score_from_summary, _market_goals, _settle_total
from signal_journal import all_signals
MOSCOW=ZoneInfo("Europe/Moscow")

def _today_rows():
    today=datetime.now(MOSCOW).date().isoformat();rows=[]
    for row in all_signals():
        try:created=datetime.fromtimestamp(int(row.get("created_ts",0)),MOSCOW)
        except Exception:continue
        if created.date().isoformat()==today:rows.append(row)
    return rows

def _live_signal_rows(rows):
    return [r for r in rows if r.get("kind")=="live" and str(r.get("reason") or "signal") in {"signal","reentry"}]

def _current_live_ids():
    try:matches=asyncio.run(discover_live_matches())
    except Exception:return None
    return {str(m.event_id) for m in matches}

def _fallback_plausibly_running(row)->bool:
    try:minute=max(0,int(row.get("minute") or 0));created=float(row.get("created_ts") or 0)
    except Exception:return True
    if created<=0:return True
    return (time.time()-created)<max(12,100-minute)*60

def build_live_signals_text()->str:
    """Compact list for the Telegram 'В игре' button: only entries whose match is LIVE now."""
    rows=_live_signal_rows(_today_rows());live_ids=_current_live_ids()
    if live_ids is None:return "⚠️ Не удалось получить LIVE-список Flashscore. Попробуй ещё раз через минуту."
    active=[r for r in rows if str(r.get("event_id","")) in live_ids]
    # One row per match: show the newest still-relevant entry, not historical duplicates.
    latest={}
    for r in active:
        eid=str(r.get("event_id",""));old=latest.get(eid)
        if old is None or int(r.get("created_ts",0) or 0)>int(old.get("created_ts",0) or 0):latest[eid]=r
    active=sorted(latest.values(),key=lambda r:int(r.get("created_ts",0) or 0),reverse=True)
    if not active:return "🟢 <b>В ИГРЕ</b>\n\nСейчас активных матчей с сигналом нет."
    lines=[f"🟢 <b>В ИГРЕ — {len(active)}</b>","<i>Только матчи, по которым был вход и которые прямо сейчас LIVE.</i>",""]
    for r in active[:20]:
        try:when=datetime.fromtimestamp(int(r.get("created_ts",0)),MOSCOW).strftime("%H:%M")
        except Exception:when="—"
        lines.append(f"🔥 <b>{r.get('home')} — {r.get('away')}</b>\n↳ вход {r.get('minute')}' · {r.get('score_at_signal')} · {when}")
    if len(active)>20:lines.append(f"\n…и ещё {len(active)-20}")
    return "\n".join(lines)

def build_report_text()->str:
    rows=_today_rows();live_rows=_live_signal_rows(rows);pre_rows=[r for r in rows if r.get("kind")=="prematch"];current_live_ids=_current_live_ids();summary_cache={}
    def get_summary(event_id):
        event_id=str(event_id or "")
        if not event_id:return None
        if event_id not in summary_cache:
            try:summary_cache[event_id]=fetch_summary(event_id)
            except Exception:summary_cache[event_id]=None
        return summary_cache[event_id]
    live_ok=live_bad=live_wait=0;live_details=[]
    for row in live_rows:
        event_id=str(row.get("event_id", ""));body=get_summary(event_id)
        try:sh,sa=map(int,str(row.get("score_at_signal","0:0")).split(":"))
        except Exception:sh=sa=0
        is_live=(current_live_ids is not None and event_id in current_live_ids);feed_unknown=(current_live_ids is None)
        if not body:live_wait+=1;mark="⏳";fh,fa=sh,sa
        else:
            try:fh,fa,_,_=_score_from_summary(body)
            except Exception:live_wait+=1;mark="⏳";fh,fa=sh,sa
            else:
                if (fh+fa)<(sh+sa):live_wait+=1;mark="⏳"
                elif (fh+fa)>(sh+sa):live_ok+=1;mark="✅"
                elif is_live:live_wait+=1;mark="⏳"
                elif feed_unknown and _fallback_plausibly_running(row):live_wait+=1;mark="⏳"
                else:live_bad+=1;mark="❌"
        reason=str(row.get("reason") or "signal");label="ПОВТОРНЫЙ ВХОД" if reason=="reentry" else "ВХОД"
        live_details.append(f"{mark} {label} · {row.get('home')} — {row.get('away')} | {row.get('minute')}' {row.get('score_at_signal')} → {fh}:{fa}")
    pre_ok=pre_bad=pre_wait=0;pre_details=[]
    for row in pre_rows:
        body=get_summary(str(row.get("event_id","")))
        if not body:pre_wait+=1;continue
        try:fh,fa,hh,ha=_score_from_summary(body);goals=_market_goals(str(row.get("scope","Матч")),fh,fa,hh,ha);res=_settle_total(str(row.get("side","ТБ")),float(row.get("line",0)),goals)
        except Exception:pre_wait+=1;continue
        if res in {"+","+½"}:pre_ok+=1;mark="✅"
        elif res in {"-","-½"}:pre_bad+=1;mark="❌"
        else:pre_wait+=1;mark="⏳"
        pre_details.append(f"{mark} {row.get('home')} — {row.get('away')} | {row.get('scope')} {row.get('side')} {row.get('line')} → {fh}:{fa}")
    settled=live_ok+live_bad;live_rate=round(live_ok/settled*100) if settled else 0
    initial=sum(1 for r in live_rows if str(r.get("reason") or "signal")=="signal");reentries=sum(1 for r in live_rows if str(r.get("reason") or "signal")=="reentry")
    lines=["📊 <b>GOOL BOT — ОТЧЁТ НА СЕЙЧАС</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🔴 <b>LIVE</b>",f"Реальных входов: <b>{len(live_rows)}</b>",f"↳ Первичных: <b>{initial}</b> · повторных после гола: <b>{reentries}</b>",f"✅ Зашло: <b>{live_ok}</b>",f"❌ Не зашло: <b>{live_bad}</b>",f"⏳ Реально ещё в LIVE: <b>{live_wait}</b>","ℹ️ Статус LIVE берётся напрямую из Flashscore; гол-подтверждения и служебные обновления сигналами не считаются."]
    if settled:lines.append(f"🎯 Проходимость завершённых входов: <b>{live_rate}%</b>")
    lines += ["","🔥 <b>ПРЕМАТЧ</b>",f"Всего сигналов: <b>{len(pre_rows)}</b>",f"✅ Сейчас проходят: <b>{pre_ok}</b>",f"❌ Сейчас не проходят: <b>{pre_bad}</b>",f"⏳ Нет данных/возврат: <b>{pre_wait}</b>"]
    if live_details:lines += ["","<b>Последние LIVE-входы:</b>"]+live_details[-12:]
    if pre_details:lines += ["","<b>Последние прематч:</b>"]+pre_details[-10:]
    if not rows:lines += ["","Сегодня в журнале пока нет сигналов."]
    return "\n".join(lines)
