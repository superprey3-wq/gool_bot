"""Strict quality gate for owner TOP-load total alerts on the live-only deploy.

Patches the real market_test_signal generator before Telegram delivery.
Rules are fail-closed and intentionally selective: only fast, well-confirmed
market moves are eligible for TOP-load delivery.
"""
from __future__ import annotations
import logging, os
import market_test_signal as mts

log=logging.getLogger("market_test_signal_strict")

MIN_BLOCKS=int(os.getenv("TOPLOAD_MIN_BLOCKS","4"))
MIN_REOPENS=int(os.getenv("TOPLOAD_MIN_REOPEN","3"))
MIN_MOVE_PP=float(os.getenv("TOPLOAD_MIN_MOVE_PP","10.0"))
MAX_MOVE_AGE=int(os.getenv("TOPLOAD_MAX_MOVE_AGE","420"))
MAX_LIVE_MINUTE=int(os.getenv("TOPLOAD_MAX_LIVE_MINUTE","75"))
LATE_FROM=int(os.getenv("TOPLOAD_LATE_FROM","60"))
LATE_MIN_BLOCKS=int(os.getenv("TOPLOAD_LATE_MIN_BLOCKS","5"))
LATE_MIN_REOPENS=int(os.getenv("TOPLOAD_LATE_MIN_REOPEN","4"))
LATE_MIN_MOVE_PP=float(os.getenv("TOPLOAD_LATE_MIN_MOVE_PP","12.0"))
LATE_MAX_MOVE_AGE=int(os.getenv("TOPLOAD_LATE_MAX_MOVE_AGE","300"))

_orig_eligible_time=mts._eligible_time
_orig_message=mts._message


def _meta(s):
    x=mts._enrich(s)
    try: minute=int(x.get("minute") or x.get("match_minute") or 0)
    except Exception: minute=0
    try: blocks=int(x.get("suspends",0) or 0)
    except Exception: blocks=0
    try: reopens=int(x.get("reopens",0) or 0)
    except Exception: reopens=0
    try: move=abs(float(x.get("delta_pp",0) or 0))
    except Exception: move=0.0
    try: age=max(0,int(x.get("elapsed",0) or 0))
    except Exception: age=10**9
    status=str(x.get("status") or x.get("state") or "").casefold()
    live=("live" in status or str(x.get("is_live") or "").casefold() in ("1","true","yes") or minute>0)
    return x,minute,blocks,reopens,move,age,live


def _strict_sharp(s):
    x,minute,blocks,reopens,move,age,live=_meta(s)
    if blocks<MIN_BLOCKS:
        log.info("TOPLOAD_REJECT reason=blocks blocks=%d min=%d",blocks,MIN_BLOCKS);return False
    if reopens<MIN_REOPENS:
        log.info("TOPLOAD_REJECT reason=reopens reopens=%d min=%d",reopens,MIN_REOPENS);return False
    if move<MIN_MOVE_PP:
        log.info("TOPLOAD_REJECT reason=move move=%.2f min=%.2f",move,MIN_MOVE_PP);return False
    if age<=0 or age>MAX_MOVE_AGE:
        log.info("TOPLOAD_REJECT reason=stale age=%d max=%d",age,MAX_MOVE_AGE);return False
    if live:
        if minute>MAX_LIVE_MINUTE:
            log.info("TOPLOAD_REJECT reason=late minute=%d max=%d",minute,MAX_LIVE_MINUTE);return False
        if minute>=LATE_FROM and (blocks<LATE_MIN_BLOCKS or reopens<LATE_MIN_REOPENS or move<LATE_MIN_MOVE_PP or age>LATE_MAX_MOVE_AGE):
            log.info("TOPLOAD_REJECT reason=late_quality minute=%d blocks=%d reopen=%d move=%.2f age=%d",minute,blocks,reopens,move,age);return False
    return True


def _strict_eligible_time(s):
    if not _orig_eligible_time(s):return False
    x,minute,blocks,reopens,move,age,live=_meta(s)
    if live and minute>MAX_LIVE_MINUTE:return False
    return True


def _strict_message(s):
    text=_orig_message(s)
    try:d=float(s.get("delta_pp",0) or 0)
    except Exception:d=0.0
    if d<0:
        text=text.replace("🎯 <b>Рекомендованное направление:</b>","🧭 <b>Рыночное направление:</b>")
        text=text.replace("<i>Кэф противоположной стороны не получен — не подставляю выдуманное значение.</i>","<i>⚠️ VALUE НЕ ПОДТВЕРЖДЁН: коэффициент противоположной стороны не получен. Это наблюдение за рынком, не готовая ставка.</i>")
    text=text.replace("<i>Только тоталы матча ТБ/ТМ · кэф от 1.35 · LIVE или старт ≤2ч · топ-5 · один сигнал на матч.</i>","<i>Фильтр PRO: ≥4 блокировок · ≥3 reopen · движение ≥10 п.п. · окно ≤420с · LIVE ≤75' · с 60' только ≥5/4, ≥12 п.п., ≤300с.</i>")
    return text

mts._sharp=_strict_sharp
mts._eligible_time=_strict_eligible_time
mts._message=_strict_message
log.info("MARKET_TEST_STRICT_GATE enabled blocks=%d reopen=%d move=%.1f age=%d max_live=%d late_from=%d",MIN_BLOCKS,MIN_REOPENS,MIN_MOVE_PP,MAX_MOVE_AGE,MAX_LIVE_MINUTE,LATE_FROM)
