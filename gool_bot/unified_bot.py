"""Unified PREMATCH + LIVE bot runner."""
from __future__ import annotations
import asyncio,json,logging,os,time
from pathlib import Path
from typing import Any
import requests
from live_engine import StatsSnapshot,calculate_goal_pressure,discover_live_matches,fetch_stats,get_previous_values,parse_stats,save_snapshot
from prematch_scanner import _fetch_event_odds
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s"); logger=logging.getLogger("unified_bot")
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN",""); CHAT_ID=os.getenv("TELEGRAM_CHAT_ID",""); LIVE_SCAN_SECONDS=int(os.getenv("LIVE_SCAN_SECONDS","60")); LIVE_SIGNAL_THRESHOLD=float(os.getenv("LIVE_SIGNAL_THRESHOLD","75")); LIVE_COOLDOWN_MINUTES=int(os.getenv("LIVE_COOLDOWN_MINUTES","12")); MIN_LIVE_ODDS=float(os.getenv("MIN_LIVE_ODDS","1.45")); TARGET_LIVE_ODDS=float(os.getenv("TARGET_LIVE_ODDS","1.75")); SENT_STATE_FILE=Path(os.getenv("LIVE_SENT_STATE_FILE","live_sent.json"))
def _load_sent():
    if not SENT_STATE_FILE.exists(): return {}
    try: return {str(k):float(v) for k,v in json.loads(SENT_STATE_FILE.read_text(encoding="utf-8")).items()}
    except Exception: return {}
def _save_sent(data):
    cutoff=time.time()-21600; SENT_STATE_FILE.write_text(json.dumps({k:v for k,v in data.items() if v>=cutoff},ensure_ascii=False),encoding="utf-8")
def telegram_send(text):
    if not BOT_TOKEN or not CHAT_ID: return False
    try: return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=15).ok
    except requests.RequestException: return False

def _best_live_total(entries:list[dict[str,Any]],total_goals:int):
    """Choose an actually interesting next over line, not the safest 1.01-style price.
    Prefer odds near TARGET_LIVE_ODDS, require MIN_LIVE_ODDS when possible.
    """
    candidates=[]
    for entry in entries:
        if str(entry.get("bettingType"))!="OVER_UNDER" or str(entry.get("bettingScope") or "FULL_TIME")!="FULL_TIME": continue
        for item in entry.get("odds") or []:
            if not isinstance(item,dict) or not item.get("active",True) or str(item.get("selection") or "").upper()!="OVER": continue
            try: line=float((item.get("handicap") or {}).get("value")); value=float(item.get("value"))
            except (TypeError,ValueError): continue
            if line<=total_goals: continue
            candidates.append((line,value))
    if not candidates: return None
    interesting=[x for x in candidates if x[1]>=MIN_LIVE_ODDS]
    pool=interesting or candidates
    line,value=min(pool,key=lambda x:(abs(x[1]-TARGET_LIVE_ODDS),abs(x[0]-(total_goals+1.5))))
    return f"ТБ {line:g}",value

def _format_signal(match,pressure,stats,odds_info):
    def pair(key):
        a,b=stats.get(key,(0,0)); return f"{a:g} — {b:g}"
    reasons="\n".join(f"• {x}" for x in pressure.reasons[:4]) or "• устойчивое давление на ворота"
    odds_line="💰 Интересный тотал: коэффициент сейчас недоступен" if not odds_info else f"💰 {odds_info[0]}: <b>{odds_info[1]:.2f}</b>"
    level="🔥 ОЧЕНЬ СИЛЬНОЕ" if pressure.score>=90 else "🔥 СИЛЬНОЕ" if pressure.score>=82 else "⚡ ПОВЫШЕННОЕ"
    league_line=f"🏆 {match.league}\n" if match.league else "🏆 Турнир: данные уточняются\n"
    status="Перерыв" if match.is_halftime else f"{match.minute}'"
    return (f"🔴 <b>LIVE-СИГНАЛ НА ГОЛ</b>\n\n⚽ <b>{match.home} — {match.away}</b>\n{league_line}⏱ {status} | Счёт {match.home_score}:{match.away_score}\n\n📊 <b>Статистика в матче</b>\nОжидаемые голы (xG): <b>{pair('xg')}</b>\nУдары: {pair('shots')}\nУдары в створ: {pair('shots_on_target')}\nБольшие голевые моменты: {pair('big_chances')}\nУдары из штрафной: {pair('shots_inside_box')}\nКасания в штрафной: {pair('touches_box')}\nУгловые: {pair('corners')}\n\n⚡ Динамика давления: <b>{pressure.momentum:.0f}/100</b>\n🔥 Давление на гол: <b>{pressure.score:.0f}/100</b>\n📈 Оценка ситуации: <b>{level}</b>\n{odds_line}\n\n🎯 <b>Возможен ещё один гол</b>\n\nПочему появился сигнал:\n{reasons}")

async def scan_live_once():
    live=await discover_live_matches(); logger.info("Найдено LIVE-матчей: %d",len(live)); sent_state=_load_sent(); sent=0
    for match in live:
        body=fetch_stats(match.event_id)
        if not body: continue
        stats=parse_stats(body)
        if not stats: continue
        previous=get_previous_values(match.event_id,match.minute,8); pressure=calculate_goal_pressure(match,stats,previous); save_snapshot(match.event_id,StatsSnapshot(int(time.time()),match.minute,stats))
        logger.info("%s - %s %d' pressure=%.1f momentum=%.1f",match.home,match.away,match.minute,pressure.score,pressure.momentum)
        # Never send a 'goal before halftime' style signal while the match is actually at HT.
        if match.is_halftime or pressure.score<LIVE_SIGNAL_THRESHOLD: continue
        now=time.time()
        if now-sent_state.get(match.event_id,0)<LIVE_COOLDOWN_MINUTES*60: continue
        odds_info=_best_live_total(_fetch_event_odds(match.event_id),match.home_score+match.away_score)
        if telegram_send(_format_signal(match,pressure,stats,odds_info)):
            sent_state[match.event_id]=now; _save_sent(sent_state); sent+=1
    logger.info("Отправлено LIVE-сигналов: %d",sent); return sent
async def main():
    logger.info("GOOL BOT запущен; интервал LIVE=%s сек, порог=%.0f",LIVE_SCAN_SECONDS,LIVE_SIGNAL_THRESHOLD)
    while True:
        try: await scan_live_once()
        except Exception as exc: logger.exception("Ошибка LIVE-цикла: %s",exc)
        await asyncio.sleep(LIVE_SCAN_SECONDS)
if __name__=="__main__": asyncio.run(main())
