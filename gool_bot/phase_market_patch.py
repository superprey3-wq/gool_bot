"""Period-aware LIVE odds presentation for GOOL Bot."""
from __future__ import annotations
import logging

import live_candidate_patch as lc
import unified_bot
from bovada_live_odds import get_first_half_total_odds

logger=logging.getLogger("phase_market_patch")
_orig_market=lc._market

# A price can be real/visible even when it is too short to recommend as a bet.
# Keep lc._sane_price() for recommendation/value selection, but do not hide a
# genuine 1.01-1.04 market from the user.
def _visible_price(row):
    try:
        return float(row.get("odd")) > 1.001
    except (TypeError, ValueError, AttributeError):
        return False


def _first_half_rows(entries,m,p):
    goals=int(m.home_score)+int(m.away_score)
    targets=(goals+.5,goals+1.5)
    ls_rows=[r for r in unified_bot._recommendations(entries,m,p)
             if r.get("scope")=="FIRST_HALF"
             and float(r.get("line",-99)) in targets
             and _visible_price(r)]
    ls_by={float(r["line"]):dict(r,source="LSApp") for r in ls_rows}
    try:
        bov=get_first_half_total_odds(m.home,m.away,m.home_score,m.away_score)
    except Exception as exc:
        logger.info("FIRST_HALF_BOVADA_FAILED %s: %s",m.event_id,exc); bov=[]
    bov_by={float(r["line"]):r for r in bov if _visible_price(r)}
    rows=[]
    for step,line in enumerate(targets,1):
        row=dict(bov_by.get(float(line)) or ls_by.get(float(line)) or {})
        if not row:continue
        row["goal_step"]=step
        row["period_label"]="1-й тайм"
        rows.append(row)
    return rows


def _market(entries,m,p):
    ft_rows,market=_orig_market(entries,m,p)
    if m.minute<=45 and not m.is_halftime:
        return _first_half_rows(entries,m,p)+ft_rows,market
    return ft_rows,market


def _row_map(recs,scope):
    return {float(r["line"]):r for r in recs if r.get("scope")==scope and _visible_price(r)}


def _period_prices(recs,m):
    goals=int(m.home_score)+int(m.away_score)
    targets=(goals+.5,goals+1.5)
    if m.minute<=45 and not m.is_halftime:
        by=_row_map(recs,"FIRST_HALF")
        title="⏱ <b>1-Й ТАЙМ</b>"
        labels=("Ещё 1 гол до перерыва","Ещё 2 гола до перерыва")
    else:
        by=_row_map(recs,"FULL_TIME")
        title="⏱ <b>ОСТАТОК МАТЧА</b>"
        labels=("Ещё 1 гол","Ещё 2 гола")
    lines=[title]
    for label,line in zip(labels,targets):
        r=by.get(float(line))
        if r:
            source=f" · {r.get('source')}" if r.get("source") else ""
            odd=float(r['odd'])
            note=" <i>(низкий кэф)</i>" if odd < lc.MIN_SANE_LIVE_ODD else ""
            lines.append(f"💰 {label}: <b>ТБ {line:g} — {odd:.2f}</b>{source}{note}")
        else:
            lines.append(f"💰 {label}: <b>ТБ {line:g} — LIVE-кэф не найден</b>")
    return "\n".join(lines)


def _format_strategy_signal(m,p,s,recs,goals,reason,route,master,hz,market):
    def pair(k):
        a,b=s.get(k,(0,0)); return f"{a:g}–{b:g}"
    status="Перерыв" if m.is_halftime else f"{m.minute}'"
    grade=lc._signal_grade(master)
    if reason=="goal":
        if m.minute>lc.MAX_FOLLOWUP_MINUTE:
            title="✅ <b>ГОЛ — СИГНАЛ СРАБОТАЛ!</b>"; action="🏁 <b>МАТЧ ЗАКРЫТ — ДАЛЬШЕ НЕ СЧИТАЮ</b>"
        else:
            title="✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>\n🔄 Матч и LIVE-линии пересчитаны"
            action="✅ <b>ГОЛ ЗАФИКСИРОВАН</b>\n👀 <b>Новый вход пока не даю — оцениваю игру заново после гола</b>"
    elif reason=="reentry":
        title="♻️ <b>НОВЫЙ ВХОД ПОСЛЕ ГОЛА</b>"
        action="🔥 <b>НОВАЯ СТАТИСТИКА ПОСЛЕ ГОЛА ПОДТВЕРЖДАЕТ ЕЩЁ ОДИН ВХОД</b>"
    elif reason=="followup":title="🔄 <b>ОБНОВЛЕНИЕ ПО МАТЧУ</b>"
    elif m.is_halftime:title="🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>"
    else:title="🔴 <b>LIVE-СИГНАЛ</b>"
    if reason not in {"goal","reentry"}:
        if grade=="STRONG":action="🔥 <b>МОЖНО ЗАХОДИТЬ — СИЛЬНЫЙ СИГНАЛ</b>"
        elif grade=="ENTRY":action="🟡 <b>МОЖНО РАССМАТРИВАТЬ ВХОД</b>"
        elif grade=="OBSERVE":action="👀 <b>НАБЛЮДАЮ МАТЧ — ПОКА БЕЗ ВХОДА</b>"
        else:action="⚪ <b>СИГНАЛ ОСЛАБ — НОВЫЙ ВХОД НЕ НУЖЕН</b>"
        if m.is_halftime and grade in ("ENTRY","STRONG"):
            action += "\n🔵 Приоритет: ещё 1 гол во 2-м тайме"
    model_goal=max(1,min(92,round(hz[3])))
    prices=_period_prices(recs,m)
    best=next((r for r in recs if r.get("best_bet") and r.get("scope")=="FULL_TIME" and lc._sane_price(r)),None)
    if m.minute<=45 and not m.is_halftime:
        best_line=(f"⭐ Лучшая ставка на весь матч: <b>ТБ {float(best['line']):g} @ {float(best['odd']):.2f}</b>"
                   if best else "⭐ Лучшая ставка на весь матч: <b>сейчас нет подходящего LIVE-кэфа</b>")
    else:
        best_line=(f"⭐ Лучшая ставка на остаток матча: <b>ТБ {float(best['line']):g} @ {float(best['odd']):.2f}</b>"
                   if best else "⭐ Лучшая ставка на остаток матча: <b>сейчас нет подходящего LIVE-кэфа</b>")
    stats=f"📊 xG {pair('xg')} | Удары {pair('shots')} | В створ {pair('shots_on_target')}"
    window=f"🧩 Отрезок: <b>{lc._window_label(m.minute)} мин</b>"
    return f"{title}\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {status} | <b>{m.home_score}:{m.away_score}</b>\n{window}\n\n{action}\n📈 Вероятность ещё гола: <b>{model_goal}%</b>\n{prices}\n{best_line}\n\n{stats}\n🧠 Рейтинг сигнала: <b>{master:.0f}/100</b>"

lc._market=_market
lc._format_strategy_signal=_format_strategy_signal
