"""Period-aware LIVE odds presentation using Flashscore/LSApp as source of truth."""
from __future__ import annotations
import live_candidate_patch as lc
import unified_bot

_orig_market=lc._market


def _visible_price(row):
    try:return float(row.get("odd"))>1.001
    except (TypeError,ValueError,AttributeError):return False


def _first_half_rows(entries,m,p):
    goals=int(m.home_score)+int(m.away_score);targets=(goals+.5,goals+1.5);rows=[]
    for r in unified_bot._recommendations(entries,m,p):
        if r.get("scope")!="FIRST_HALF" or not _visible_price(r):continue
        try:line=float(r.get("line"))
        except (TypeError,ValueError):continue
        if line not in targets:continue
        step=1 if abs(line-targets[0])<1e-9 else 2
        rows.append(dict(r,source="Flashscore/LSApp",primary_source=True,goal_step=step,period_label="1-й тайм"))
    return rows


def _market(entries,m,p):
    ft_rows,market=_orig_market(entries,m,p)
    if int(m.minute or 0)<=45 and not m.is_halftime:return _first_half_rows(entries,m,p)+ft_rows,market
    return ft_rows,market


def _row_map(recs,scope):
    out={}
    for r in recs:
        if r.get("scope")!=scope or not _visible_price(r) or r.get("line") is None:continue
        try:out[float(r["line"])]=r
        except (TypeError,ValueError):pass
    return out


def _period_prices(recs,m):
    goals=int(m.home_score)+int(m.away_score);targets=(goals+.5,goals+1.5)
    first=int(m.minute or 0)<=45 and not m.is_halftime;scope="FIRST_HALF" if first else "FULL_TIME";by=_row_map(recs,scope)
    title="⏱ <b>1-Й ТАЙМ</b>" if first else "⏱ <b>ОСТАТОК МАТЧА</b>";labels=("Ещё 1 гол до перерыва","Ещё 2 гола до перерыва") if first else ("Ещё 1 гол","Ещё 2 гола")
    lines=[title]
    for label,line in zip(labels,targets):
        r=by.get(float(line))
        if r:
            odd=float(r['odd']);note=" <i>(низкий кэф)</i>" if odd<lc.MIN_SANE_LIVE_ODD else ""
            lines.append(f"💰 {label}: <b>ТБ {line:g} — {odd:.2f}</b> · Flashscore/LSApp{note}")
        else:lines.append(f"💰 {label}: <b>ТБ {line:g} — LIVE-кэф не найден</b>")
    return "\n".join(lines)


def _format_strategy_signal(m,p,s,recs,goals,reason,route,master,hz,market):
    def pair(k):a,b=s.get(k,(0,0));return f"{a:g}–{b:g}"
    status="Перерыв" if m.is_halftime else f"{m.minute}'";grade=lc._signal_grade(master)
    if reason=="goal":title="✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>";action="✅ <b>ГОЛ ЗАФИКСИРОВАН</b>"
    elif reason=="reentry":title="♻️ <b>НОВЫЙ ВХОД ПОСЛЕ ГОЛА</b>";action="🔥 <b>НОВАЯ СТАТИСТИКА ПОДТВЕРЖДАЕТ ЕЩЁ ОДИН ВХОД</b>"
    elif reason=="followup":title="🔄 <b>ОБНОВЛЕНИЕ ПО МАТЧУ</b>";action="👀 <b>ПЕРЕСЧЁТ LIVE</b>"
    elif m.is_halftime:title="🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>";action="🔥 <b>МОЖНО ЗАХОДИТЬ</b>" if grade in {"ENTRY","STRONG"} else "👀 <b>НАБЛЮДАЮ</b>"
    else:title="🔴 <b>LIVE-СИГНАЛ</b>";action="🔥 <b>МОЖНО ЗАХОДИТЬ</b>" if grade in {"ENTRY","STRONG"} else "👀 <b>НАБЛЮДАЮ МАТЧ</b>"
    model_goal=max(1,min(92,round(hz[3])));prices=_period_prices(recs,m)
    best=next((r for r in recs if r.get("best_bet") and r.get("scope")=="FULL_TIME" and lc._sane_price(r)),None)
    best_line=f"⭐ Лучшая ставка: <b>ТБ {float(best['line']):g} @ {float(best['odd']):.2f}</b> · Flashscore/LSApp" if best else "⭐ Лучшая ставка: <b>нет подходящего LIVE-рынка</b>"
    stats=f"📊 xG {pair('xg')} | Удары {pair('shots')} | В створ {pair('shots_on_target')}"
    return f"{title}\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {status} | <b>{m.home_score}:{m.away_score}</b>\n🧩 Отрезок: <b>{lc._window_label(m.minute)} мин</b>\n\n{action}\n📈 Вероятность ещё гола: <b>{model_goal}%</b>\n{prices}\n{best_line}\n\n{stats}\n🧠 Рейтинг сигнала: <b>{master:.0f}/100</b>"

lc._market=_market
lc._format_strategy_signal=_format_strategy_signal
