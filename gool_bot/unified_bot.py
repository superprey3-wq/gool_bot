"""Unified PREMATCH + LIVE bot runner."""
from __future__ import annotations
import asyncio,json,logging,os,time
from pathlib import Path
from typing import Any
import requests
from live_engine import StatsSnapshot,calculate_goal_pressure,discover_live_matches,fetch_stats,get_previous_values,parse_stats,save_snapshot
from prematch_scanner import _fetch_event_odds
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s"); logger=logging.getLogger("unified_bot")
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN",""); CHAT_ID=os.getenv("TELEGRAM_CHAT_ID",""); LIVE_SCAN_SECONDS=int(os.getenv("LIVE_SCAN_SECONDS","60")); LIVE_SIGNAL_THRESHOLD=float(os.getenv("LIVE_SIGNAL_THRESHOLD","75")); LIVE_COOLDOWN_MINUTES=int(os.getenv("LIVE_COOLDOWN_MINUTES","12")); SENT_STATE_FILE=Path(os.getenv("LIVE_SENT_STATE_FILE","live_sent.json"))
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

def _model_confidence(pressure_score:float,momentum:float,line:float,current_goals:int,scope:str)->int:
    """Heuristic confidence score, not a calibrated probability."""
    base=48+pressure_score*0.28+momentum*0.12
    if scope=="SECOND_HALF": base+=3
    extra_needed=max(0.0,line-current_goals)
    base-=max(0.0,extra_needed-0.5)*13
    return max(45,min(94,round(base)))

def _recommendations(entries:list[dict[str,Any]],match,pressure):
    """Return up to 3 real LSApp over markets ranked by model confidence and price.
    At halftime prefer SECOND_HALF totals; otherwise use FULL_TIME totals.
    """
    wanted_scope="SECOND_HALF" if match.is_halftime else "FULL_TIME"
    current_goals=0 if wanted_scope=="SECOND_HALF" else match.home_score+match.away_score
    recs=[]
    for entry in entries:
        if str(entry.get("bettingType"))!="OVER_UNDER": continue
        if str(entry.get("bettingScope") or "FULL_TIME")!=wanted_scope: continue
        for item in entry.get("odds") or []:
            if not isinstance(item,dict) or not item.get("active",True) or str(item.get("selection") or "").upper()!="OVER": continue
            try: line=float((item.get("handicap") or {}).get("value")); odd=float(item.get("value"))
            except (TypeError,ValueError): continue
            if line<=current_goals or odd<=1.01: continue
            conf=_model_confidence(pressure.score,pressure.momentum,line,current_goals,wanted_scope)
            # Prefer usable odds and avoid duplicate bookmaker rows for the same line by keeping best price.
            recs.append({"scope":wanted_scope,"line":line,"odd":odd,"confidence":conf})
    best_by_line={}
    for r in recs:
        key=r["line"]
        if key not in best_by_line or r["odd"]>best_by_line[key]["odd"]: best_by_line[key]=r
    rows=list(best_by_line.values())
    rows.sort(key=lambda r:(-(r["confidence"]),abs(r["odd"]-1.80)))
    # Build a balanced set: safest useful option, main option, aggressive option.
    useful=[r for r in rows if r["odd"]>=1.20]
    return (useful or rows)[:3]

def _format_signal(match,pressure,stats,recs):
    def pair(key):
        a,b=stats.get(key,(0,0)); return f"{a:g} — {b:g}"
    reasons="\n".join(f"• {x}" for x in pressure.reasons[:4]) or "• устойчивое давление на ворота"
    league_line=f"🏆 {match.league}\n" if match.league else "🏆 Турнир: данные уточняются\n"
    status="Перерыв" if match.is_halftime else f"{match.minute}'"
    title="🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>" if match.is_halftime else "🔴 <b>LIVE-СИГНАЛ НА ГОЛ</b>"
    bet_lines=[]
    for i,r in enumerate(recs,1):
        scope_label="2-й тайм" if r["scope"]=="SECOND_HALF" else "матч"
        bet_lines.append(f"{i}. <b>ТБ {r['line']:g} ({scope_label})</b> — кэф <b>{r['odd']:.2f}</b> | уверенность модели <b>{r['confidence']}%</b>")
    bets="\n".join(bet_lines) if bet_lines else "Рынки тоталов сейчас недоступны."
    note="\n<i>Процент — оценка модели по текущей статистике, а не гарантированная вероятность.</i>"
    return (f"{title}\n\n⚽ <b>{match.home} — {match.away}</b>\n{league_line}⏱ {status} | Счёт {match.home_score}:{match.away_score}\n\n📊 <b>Статистика</b>\nОжидаемые голы (xG): <b>{pair('xg')}</b>\nУдары: {pair('shots')}\nУдары в створ: {pair('shots_on_target')}\nБольшие голевые моменты: {pair('big_chances')}\nУдары из штрафной: {pair('shots_inside_box')}\nКасания в штрафной: {pair('touches_box')}\nУгловые: {pair('corners')}\n\n⚡ Динамика давления: <b>{pressure.momentum:.0f}/100</b>\n🔥 Давление на гол: <b>{pressure.score:.0f}/100</b>\n\n🎯 <b>Рекомендованные варианты</b>\n{bets}\n\nПочему модель заинтересовалась матчем:\n{reasons}{note}")

async def scan_live_once():
    live=await discover_live_matches(); logger.info("Найдено LIVE-матчей: %d",len(live)); sent_state=_load_sent(); sent=0
    for match in live:
        body=fetch_stats(match.event_id)
        if not body: continue
        stats=parse_stats(body)
        if not stats: continue
        previous=get_previous_values(match.event_id,match.minute,8); pressure=calculate_goal_pressure(match,stats,previous); save_snapshot(match.event_id,StatsSnapshot(int(time.time()),match.minute,stats))
        logger.info("%s - %s %d' pressure=%.1f momentum=%.1f",match.home,match.away,match.minute,pressure.score,pressure.momentum)
        # At halftime we can still send a second-half forecast if first-half pressure was strong.
        if pressure.score<LIVE_SIGNAL_THRESHOLD: continue
        now=time.time(); cooldown_key=f"{match.event_id}:HT" if match.is_halftime else match.event_id
        if now-sent_state.get(cooldown_key,0)<LIVE_COOLDOWN_MINUTES*60: continue
        entries=_fetch_event_odds(match.event_id); recs=_recommendations(entries,match,pressure)
        if telegram_send(_format_signal(match,pressure,stats,recs)):
            sent_state[cooldown_key]=now; _save_sent(sent_state); sent+=1
    logger.info("Отправлено LIVE-сигналов: %d",sent); return sent
async def main():
    logger.info("GOOL BOT запущен; интервал LIVE=%s сек, порог=%.0f",LIVE_SCAN_SECONDS,LIVE_SIGNAL_THRESHOLD)
    while True:
        try: await scan_live_once()
        except Exception as exc: logger.exception("Ошибка LIVE-цикла: %s",exc)
        await asyncio.sleep(LIVE_SCAN_SECONDS)
if __name__=="__main__": asyncio.run(main())
