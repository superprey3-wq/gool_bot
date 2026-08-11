"""Unified PREMATCH + LIVE bot runner."""
from __future__ import annotations
import asyncio, json, logging, os, time
from pathlib import Path
from typing import Any
import requests
from live_engine import StatsSnapshot, calculate_goal_pressure, discover_live_matches, fetch_stats, fetch_summary, get_previous_values, parse_goal_timeline, parse_stats, save_snapshot
from prematch_scanner import _fetch_event_odds

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("unified_bot")
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN",""); CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","")
LIVE_SIGNAL_THRESHOLD=float(os.getenv("LIVE_SIGNAL_THRESHOLD","75")); LIVE_COOLDOWN_MINUTES=int(os.getenv("LIVE_COOLDOWN_MINUTES","12"))
SENT_STATE_FILE=Path(os.getenv("LIVE_SENT_STATE_FILE","live_sent.json"))

def _load_sent():
    if not SENT_STATE_FILE.exists(): return {}
    try:
        data=json.loads(SENT_STATE_FILE.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {}
    except Exception: return {}
def _save_sent(data):
    cutoff=time.time()-8*3600; clean={}
    for k,v in data.items():
        if isinstance(v,dict):
            ts=float(v.get("ts",v.get("tracked_since",0)) or 0)
            if ts>=cutoff: clean[k]=v
    SENT_STATE_FILE.write_text(json.dumps(clean,ensure_ascii=False),encoding="utf-8")
def telegram_send(text):
    if not BOT_TOKEN or not CHAT_ID:return False
    try:return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=15).ok
    except requests.RequestException:return False

def _model_confidence(pressure_score:float,momentum:float,line:float,current_goals:int,scope:str,minute:int)->int:
    base=48+pressure_score*.28+momentum*.12
    if scope=="SECOND_HALF":base+=3
    base-=max(0.0,(line-current_goals)-.5)*13
    if minute>=80: base-=12
    elif minute>=75: base-=6
    return max(35,min(94,round(base)))
def _recommendations(entries:list[dict[str,Any]],match,pressure):
    scope="SECOND_HALF" if match.is_halftime else "FULL_TIME"; goals=0 if scope=="SECOND_HALF" else match.home_score+match.away_score; recs=[]
    for entry in entries:
        if str(entry.get("bettingType"))!="OVER_UNDER" or str(entry.get("bettingScope") or "FULL_TIME")!=scope:continue
        for item in entry.get("odds") or []:
            if not isinstance(item,dict) or not item.get("active",True) or str(item.get("selection") or "").upper()!="OVER":continue
            try:line=float((item.get("handicap") or {}).get("value")); odd=float(item.get("value"))
            except (TypeError,ValueError):continue
            if line<=goals or odd<=1.01:continue
            recs.append({"scope":scope,"line":line,"odd":odd,"confidence":_model_confidence(pressure.score,pressure.momentum,line,goals,scope,match.minute)})
    best={}
    for r in recs:
        if r["line"] not in best or r["odd"]>best[r["line"]]["odd"]:best[r["line"]]=r
    rows=list(best.values()); rows.sort(key=lambda r:(-r["confidence"],abs(r["odd"]-1.8))); useful=[r for r in rows if r["odd"]>=1.20]
    return (useful or rows)[:3]
def _format_signal(match,pressure,stats,recs,goal_times,reason="signal"):
    def pair(k):a,b=stats.get(k,(0,0)); return f"{a:g} — {b:g}"
    league=f"🏆 {match.league}\n" if match.league else "🏆 Турнир: данные уточняются\n"; status="Перерыв" if match.is_halftime else f"{match.minute}'"
    title="⚽ <b>ГОЛ — МАТЧ ПЕРЕСЧИТАН</b>" if reason=="goal" else "🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>" if match.is_halftime else "🔄 <b>ОБНОВЛЕНИЕ ПО МАТЧУ</b>" if reason=="followup" else "🔴 <b>LIVE-СИГНАЛ НА ГОЛ</b>"
    goals_line=f"⚽ Голы: <b>{', '.join(goal_times)}</b>\n" if goal_times else "⚽ Голы: пока нет\n"
    late_warning=""
    if match.minute>=80:
        late_warning="\n⚠️ <b>ОСОБО ВЫСОКИЙ РИСК: 80+ минута.</b> Времени мало, даже при сильном давлении вход значительно опаснее.\n"
    elif match.minute>=75:
        late_warning="\n⚠️ <b>ПОВЫШЕННЫЙ РИСК: поздняя стадия матча.</b>\n"
    bet_lines=[]
    for i,r in enumerate(recs,1):
        label="2-й тайм" if r["scope"]=="SECOND_HALF" else "матч"; bet_lines.append(f"{i}. <b>ТБ {r['line']:g} ({label})</b> — кэф <b>{r['odd']:.2f}</b> | уверенность модели <b>{r['confidence']}%</b>")
    bets="\n".join(bet_lines) if bet_lines else "Сейчас подходящего рынка тоталов нет."; verdict="🔥 Давление сохраняется, матч остаётся интересным." if pressure.score>=LIVE_SIGNAL_THRESHOLD else "⚠️ После изменения матча давление ниже порога — новый вход сейчас не подтверждён."; reasons="\n".join(f"• {x}" for x in pressure.reasons[:4]) or "• текущая динамика без сильного всплеска"
    return f"{title}\n\n⚽ <b>{match.home} — {match.away}</b>\n{league}⏱ {status} | Счёт <b>{match.home_score}:{match.away_score}</b>\n{goals_line}{late_warning}\n📊 <b>Статистика</b>\nxG: <b>{pair('xg')}</b>\nУдары: {pair('shots')}\nУдары в створ: {pair('shots_on_target')}\nБольшие моменты: {pair('big_chances')}\nУдары из штрафной: {pair('shots_inside_box')}\nКасания в штрафной: {pair('touches_box')}\nУгловые: {pair('corners')}\n\n⚡ Динамика: <b>{pressure.momentum:.0f}/100</b>\n🔥 Давление на гол: <b>{pressure.score:.0f}/100</b>\n{verdict}\n\n🎯 <b>Варианты</b>\n{bets}\n\n{reasons}\n<i>Процент — оценка модели, а не гарантированная вероятность.</i>"

async def scan_live_once():
    live=await discover_live_matches(); state=_load_sent(); sent=0; live_ids={m.event_id for m in live}
    for key in list(state):
        if key.startswith("TRACK:") and key.split(":",1)[1] not in live_ids:state.pop(key,None)
    for match in live:
        body=fetch_stats(match.event_id)
        if not body:continue
        stats=parse_stats(body)
        if not stats:continue
        previous=get_previous_values(match.event_id,match.minute,8); pressure=calculate_goal_pressure(match,stats,previous); save_snapshot(match.event_id,StatsSnapshot(int(time.time()),match.minute,stats)); goal_times=parse_goal_timeline(fetch_summary(match.event_id))
        now=time.time(); track_key=f"TRACK:{match.event_id}"; tracked=state.get(track_key); current_score=f"{match.home_score}:{match.away_score}"
        if not tracked:
            if pressure.score<LIVE_SIGNAL_THRESHOLD:continue
            recs=_recommendations(_fetch_event_odds(match.event_id),match,pressure)
            if telegram_send(_format_signal(match,pressure,stats,recs,goal_times,"signal")):
                state[track_key]={"tracked_since":now,"ts":now,"score":current_score,"minute":match.minute,"pressure":pressure.score,"halftime_sent":match.is_halftime}; sent+=1
            continue
        previous_score=str(tracked.get("score",current_score)); score_changed=previous_score!=current_score; halftime_new=match.is_halftime and not bool(tracked.get("halftime_sent")); last_ts=float(tracked.get("ts",0)); last_pressure=float(tracked.get("pressure",0)); pressure_jump=pressure.score>=LIVE_SIGNAL_THRESHOLD and pressure.score>=last_pressure+8; regular_followup=pressure.score>=LIVE_SIGNAL_THRESHOLD and now-last_ts>=LIVE_COOLDOWN_MINUTES*60
        if score_changed or halftime_new or pressure_jump or regular_followup:
            reason="goal" if score_changed else "followup"; recs=_recommendations(_fetch_event_odds(match.event_id),match,pressure)
            if telegram_send(_format_signal(match,pressure,stats,recs,goal_times,reason)):
                tracked.update({"ts":now,"score":current_score,"minute":match.minute,"pressure":pressure.score,"halftime_sent":bool(tracked.get("halftime_sent")) or match.is_halftime}); state[track_key]=tracked; sent+=1
        else:
            tracked.update({"score":current_score,"minute":match.minute}); state[track_key]=tracked
    _save_sent(state); logger.info("Отправлено LIVE-сигналов/обновлений: %d; сопровождается матчей: %d",sent,sum(1 for k in state if k.startswith('TRACK:'))); return sent
if __name__=="__main__":asyncio.run(scan_live_once())
