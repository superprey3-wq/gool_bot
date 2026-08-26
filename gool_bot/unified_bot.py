"""Unified GOOL LIVE bot runner."""
from __future__ import annotations
import asyncio, json, logging, math, os, statistics, time
from pathlib import Path
from typing import Any
import requests
from live_engine import StatsSnapshot, calculate_goal_pressure, discover_live_matches, fetch_stats, fetch_summary, get_previous_values, parse_goal_timeline, parse_stats, save_snapshot
from live_odds import fetch_live_odds as _fetch_event_odds
from signal_journal import add_signal

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

def telegram_send_signal(match, pressure, recs, text):
    if not BOT_TOKEN or not CHAT_ID:return False
    try:
        from signal_card import render_signal_card
        png=render_signal_card(match,pressure,recs)
        r=requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",data={"chat_id":CHAT_ID},files={"photo":("gool-live.png",png,"image/png")},timeout=20)
        if not r.ok: logger.warning("Signal card upload failed: HTTP %s %s",r.status_code,r.text[:200])
    except Exception as e: logger.warning("Signal card render/send failed: %s",e)
    return telegram_send(text)

def _minutes_remaining(scope:str, minute:int)->float:
    minute=max(0,int(minute or 0))
    if scope=="FIRST_HALF":return max(0.0,47.0-minute)
    if scope=="SECOND_HALF":return max(0.0,94.0-minute)
    return max(0.0,94.0-minute)
def _goals_needed_for_over(line:float,current_goals:int)->int:return max(1,math.floor(float(line)-float(current_goals))+1)
def _poisson_tail(lam:float,needed:int)->float:
    if needed<=0:return 1.0
    lam=max(0.0,float(lam)); cumulative=0.0; term=math.exp(-lam); cumulative+=term
    for k in range(1,needed):term*=lam/k; cumulative+=term
    return max(0.0,min(1.0,1.0-cumulative))
def _live_over_probability(pressure_score:float,momentum:float,line:float,current_goals:int,scope:str,minute:int,odd:float|None=None)->float:
    mins=_minutes_remaining(scope,minute); needed=_goals_needed_for_over(line,current_goals)
    if mins<=0:return 0.0
    base_rate=2.70/90.0; pressure_mult=0.60+1.35*max(0.0,min(1.0,pressure_score/100.0)); momentum_mult=0.85+0.30*max(0.0,min(1.0,momentum/100.0)); lam=base_rate*mins*pressure_mult*momentum_mult; model_p=_poisson_tail(lam,needed)
    if odd and odd>1.01:
        market_p=max(0.01,min(0.95,1.0/odd)); market_weight=0.55 if minute>=80 else 0.45 if minute>=70 else 0.35; model_p=model_p*(1.0-market_weight)+market_p*market_weight
    if minute>=88:model_p*=0.90
    elif minute>=85:model_p*=0.95
    return max(0.01,min(0.94,model_p))
def _model_confidence(pressure_score:float,momentum:float,line:float,current_goals:int,scope:str,minute:int,odd:float|None=None)->int:return round(_live_over_probability(pressure_score,momentum,line,current_goals,scope,minute,odd)*100)
def _scope_current_goals(match,scope:str)->int:
    if scope=="SECOND_HALF" and match.is_halftime:return 0
    return match.home_score+match.away_score
def _collect_scope_recommendations(entries:list[dict[str,Any]],match,pressure,scope:str):
    current_goals=_scope_current_goals(match,scope); buckets:dict[float,list[float]]={}
    for entry in entries:
        if str(entry.get("bettingType"))!="OVER_UNDER":continue
        if str(entry.get("bettingScope") or "FULL_TIME")!=scope:continue
        for item in entry.get("odds") or []:
            if not isinstance(item,dict) or not item.get("active",True):continue
            if str(item.get("selection") or "").upper()!="OVER":continue
            try:line=float((item.get("handicap") or {}).get("value")); odd=float(item.get("value"))
            except (TypeError,ValueError,AttributeError):continue
            if line<=current_goals or odd<=1.01:continue
            buckets.setdefault(line,[]).append(odd)
    rows=[]
    for line,prices in buckets.items():
        odd=float(statistics.median(prices)); rows.append({"scope":scope,"line":line,"odd":odd,"bookmakers":len(prices),"confidence":_model_confidence(pressure.score,pressure.momentum,line,current_goals,scope,match.minute,odd)})
    rows.sort(key=lambda r:(abs(r["odd"]-1.80),-r["confidence"])); return rows[:3]
def _recommendations(entries:list[dict[str,Any]],match,pressure):
    if match.minute<=45 and not match.is_halftime:return _collect_scope_recommendations(entries,match,pressure,"FIRST_HALF")+_collect_scope_recommendations(entries,match,pressure,"FULL_TIME")
    if match.is_halftime:return _collect_scope_recommendations(entries,match,pressure,"SECOND_HALF")+_collect_scope_recommendations(entries,match,pressure,"FULL_TIME")
    return _collect_scope_recommendations(entries,match,pressure,"FULL_TIME")
def _format_bets(recs):
    if not recs:return "Сейчас подходящего рынка тоталов нет."
    groups=[]; labels={"FIRST_HALF":"🕐 <b>ДО КОНЦА 1-ГО ТАЙМА</b>","SECOND_HALF":"🕑 <b>2-Й ТАЙМ</b>","FULL_TIME":"⚽ <b>ДО КОНЦА МАТЧА</b>"}
    for scope in ("FIRST_HALF","SECOND_HALF","FULL_TIME"):
        rows=[r for r in recs if r["scope"]==scope]
        if not rows:continue
        lines=[labels[scope]]
        for r in rows:
            books=f" · {r['bookmakers']} БК" if r.get("bookmakers") else ""; lines.append(f"ТБ {r['line']:g} — кэф <b>{r['odd']:.2f}</b> | вероятность модели <b>{r['confidence']}%</b>{books}")
        groups.append("\n".join(lines))
    return "\n\n".join(groups)
def _format_signal(match,pressure,stats,recs,goal_times,reason="signal"):
    def pair(k):a,b=stats.get(k,(0,0)); return f"{a:g} — {b:g}"
    league=f"🏆 {match.league}\n" if match.league else "🏆 Турнир: данные уточняются\n"; status="Перерыв" if match.is_halftime else f"{match.minute}'"
    title="⚽ <b>ГОЛ — МАТЧ ПЕРЕСЧИТАН</b>" if reason=="goal" else "🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>" if match.is_halftime else "🔄 <b>ОБНОВЛЕНИЕ ПО МАТЧУ</b>" if reason=="followup" else "🔴 <b>LIVE-СИГНАЛ НА ГОЛ</b>"
    goals_line=f"⚽ Голы: <b>{', '.join(goal_times)}</b>\n" if goal_times else "⚽ Голы: пока нет\n"; bets=_format_bets(recs); verdict="🔥 Давление сохраняется, матч остаётся интересным." if pressure.score>=LIVE_SIGNAL_THRESHOLD else "⚠️ После изменения матча давление ниже порога — новый вход сейчас не подтверждён."; reasons="\n".join(f"• {x}" for x in pressure.reasons[:4]) or "• текущая динамика без сильного всплеска"
    return f"{title}\n\n⚽ <b>{match.home} — {match.away}</b>\n{league}⏱ {status} | Счёт <b>{match.home_score}:{match.away_score}</b>\n{goals_line}\n📊 <b>Статистика</b>\nxG: <b>{pair('xg')}</b>\nУдары: {pair('shots')}\nУдары в створ: {pair('shots_on_target')}\n\n🔥 Давление на гол: <b>{pressure.score:.0f}/100</b>\n{verdict}\n\n🎯 <b>Варианты</b>\n{bets}\n\n{reasons}"
def _record_live(match,pressure,stats,recs,reason):
    primary=next((r for r in recs if r["scope"]=="FULL_TIME"),recs[0] if recs else None); key=f"live:{match.event_id}:{match.minute}:{match.home_score}:{match.away_score}:{reason}"; add_signal({"kind":"live","event_id":match.event_id,"home":match.home,"away":match.away,"league":match.league,"minute":match.minute,"score_at_signal":f"{match.home_score}:{match.away_score}","pressure":pressure.score,"momentum":pressure.momentum,"stats":stats,"primary":primary,"reason":reason},key)
async def scan_live_once():
    live=await discover_live_matches(); logger.info("Найдено LIVE-матчей: %d",len(live)); state=_load_sent(); sent=0; live_ids={m.event_id for m in live}
    for key in list(state):
        if key.startswith("TRACK:") and key.split(":",1)[1] not in live_ids:state.pop(key,None)
    for match in live:
        body=fetch_stats(match.event_id)
        if not body:continue
        stats=parse_stats(body)
        if not stats:continue
        previous=get_previous_values(match.event_id,match.minute,8); pressure=calculate_goal_pressure(match,stats,previous); save_snapshot(match.event_id,StatsSnapshot(int(time.time()),match.minute,stats)); goal_times=parse_goal_timeline(fetch_summary(match.event_id)); now=time.time(); track_key=f"TRACK:{match.event_id}"; tracked=state.get(track_key); current_score=f"{match.home_score}:{match.away_score}"
        if not tracked:
            if pressure.score<LIVE_SIGNAL_THRESHOLD:continue
            recs=_recommendations(_fetch_event_odds(match.event_id),match,pressure); text=_format_signal(match,pressure,stats,recs,goal_times,"signal")
            if telegram_send_signal(match,pressure,recs,text):_record_live(match,pressure,stats,recs,"signal"); state[track_key]={"tracked_since":now,"ts":now,"score":current_score,"minute":match.minute,"pressure":pressure.score,"halftime_sent":match.is_halftime}; sent+=1
            continue
        previous_score=str(tracked.get("score",current_score)); score_changed=previous_score!=current_score
        if score_changed:
            recs=_recommendations(_fetch_event_odds(match.event_id),match,pressure); text=_format_signal(match,pressure,stats,recs,goal_times,"goal")
            if telegram_send_signal(match,pressure,recs,text):_record_live(match,pressure,stats,recs,"goal"); tracked.update({"ts":now,"score":current_score,"minute":match.minute,"pressure":pressure.score,"halftime_sent":bool(tracked.get("halftime_sent")) or match.is_halftime}); state[track_key]=tracked; sent+=1
        else:
            tracked.update({"score":current_score,"minute":match.minute,"pressure":pressure.score,"halftime_sent":bool(tracked.get("halftime_sent")) or match.is_halftime}); state[track_key]=tracked
            logger.info("LIVE_REPEAT_BLOCK event=%s score=%s minute=%s pressure=%.1f reason=no_new_goal",match.event_id,current_score,match.minute,pressure.score)
    _save_sent(state); logger.info("Отправлено LIVE-сигналов/обновлений: %d; сопровождается матчей: %d",sent,sum(1 for k in state if k.startswith('TRACK:'))); return sent
if __name__=="__main__":asyncio.run(scan_live_once())