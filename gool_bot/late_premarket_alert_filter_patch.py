"""Final smart outbound gate for TOP-load total alerts.

A raw odds move is market information, not automatically a betting recommendation.
This guard is deliberately conservative:
- known market blocks=0 => suppress;
- LIVE later than 85' => suppress as late/time-decay noise;
- require a meaningful implied-probability move and either reopen evidence or
  multiple market blocks;
- never present the opposite side as a recommended bet when its actual price was
  not obtained.

The producer may live outside this repository, so this module protects the final
Telegram path as well as improving legacy card wording.
"""
from __future__ import annotations
import logging
import os
import re
import visual_feed_unified_bot as vf

logger=logging.getLogger("smart_topload_alert_filter")

_orig_send_text=vf._send_text
_orig_send_text_to_chat=vf._send_text_to_chat

_TOP_MARKER="ТОП-ПРОГРУЗ ТОТАЛА"
_LIVE_MINUTE_RE=re.compile(r"\bLIVE\s*·\s*(\d{1,3})'",re.IGNORECASE)
_BLOCK_RE=re.compile(r"Блокировок рынка:\s*(\d+)\s*·\s*reopen:\s*(\d+)",re.IGNORECASE)
_CHANGE_RE=re.compile(r"Изменение:\s*([+-]?\d+(?:[.,]\d+)?)\s*п\.п\.",re.IGNORECASE)
_NO_OPPOSITE="Кэф противоположной стороны не получен"
_RECOMMEND_RE=re.compile(r"^🎯\s*Рекомендованное направление:\s*(.+)$",re.MULTILINE)

MAX_LIVE_MINUTE=int(os.getenv("TOPLOAD_MAX_LIVE_MINUTE","85"))
MIN_MOVE_PP=float(os.getenv("TOPLOAD_MIN_MOVE_PP","4.5"))


def _parse(text):
    text=str(text or "")
    if _TOP_MARKER not in text:return None
    minute=None;blocks=None;reopen=None;move=None
    m=_LIVE_MINUTE_RE.search(text)
    if m:minute=int(m.group(1))
    b=_BLOCK_RE.search(text)
    if b:blocks,reopen=int(b.group(1)),int(b.group(2))
    c=_CHANGE_RE.search(text)
    if c:
        try:move=float(c.group(1).replace(",","."))
        except ValueError:move=None
    return {"minute":minute,"blocks":blocks,"reopen":reopen,"move":move}


def _decision(text):
    meta=_parse(text)
    if meta is None:return "PASS",text
    minute=meta["minute"];blocks=meta["blocks"];reopen=meta["reopen"];move=meta["move"]

    if blocks is not None and blocks<1:
        logger.info("TOP_LOAD_SUPPRESS reason=zero_blocks")
        return "SUPPRESS",text
    if minute is not None and minute>MAX_LIVE_MINUTE:
        logger.info("TOP_LOAD_SUPPRESS reason=late_live minute=%d max=%d",minute,MAX_LIVE_MINUTE)
        return "SUPPRESS",text
    if move is not None and abs(move)<MIN_MOVE_PP:
        logger.info("TOP_LOAD_SUPPRESS reason=weak_move move=%.2f min=%.2f",move,MIN_MOVE_PP)
        return "SUPPRESS",text
    if blocks is not None and reopen is not None and blocks<2 and reopen<1:
        logger.info("TOP_LOAD_SUPPRESS reason=weak_market_evidence blocks=%d reopen=%d",blocks,reopen)
        return "SUPPRESS",text

    # A move against one side is not proof that the opposite side is value.
    # When the opposite price is absent, downgrade the card from recommendation
    # to market observation instead of inventing a bet.
    if _NO_OPPOSITE in text:
        text=_RECOMMEND_RE.sub("🧭 Рыночное направление: \\1",text)
        text=text.replace(
            _NO_OPPOSITE+" — не подставляю выдуманное значение.",
            "⚠️ VALUE НЕ ПОДТВЕРЖДЁН: коэффициент противоположной стороны не получен. Это наблюдение за рынком, не готовая ставка.",
        )
    label="CONFIRMED STEAM" if (blocks or 0)>=2 and (reopen or 0)>=1 else "STRONG MOVE"
    if f"🧠 Статус: {label}" not in text:
        text=text.replace("🚨 ТОП-ПРОГРУЗ ТОТАЛА",f"🚨 ТОП-ПРОГРУЗ ТОТАЛА\n🧠 Статус: {label}",1)
    return "PASS",text


def _send_text(text):
    action,text=_decision(text)
    if action=="SUPPRESS":return False
    return _orig_send_text(text)


def _send_text_to_chat(token,chat_id,text):
    action,text=_decision(text)
    if action=="SUPPRESS":return False
    return _orig_send_text_to_chat(token,chat_id,text)


vf._send_text=_send_text
vf._send_text_to_chat=_send_text_to_chat
logger.info("SMART_TOPLOAD_GATE enabled max_live=%d min_move_pp=%.1f",MAX_LIVE_MINUTE,MIN_MOVE_PP)
