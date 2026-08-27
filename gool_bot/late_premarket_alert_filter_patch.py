"""Smart outbound gate for TOP-load total alerts on the deploy branch."""
from __future__ import annotations
import logging, os, re
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
def _decision(text):
 text=str(text or "")
 if _TOP_MARKER not in text:return "PASS",text
 m=_LIVE_MINUTE_RE.search(text); minute=int(m.group(1)) if m else None
 b=_BLOCK_RE.search(text); blocks=int(b.group(1)) if b else None; reopen=int(b.group(2)) if b else None
 c=_CHANGE_RE.search(text)
 try: move=float(c.group(1).replace(",",".")) if c else None
 except ValueError: move=None
 if blocks is not None and blocks<1:return "SUPPRESS",text
 if minute is not None and minute>MAX_LIVE_MINUTE:return "SUPPRESS",text
 if move is not None and abs(move)<MIN_MOVE_PP:return "SUPPRESS",text
 if blocks is not None and reopen is not None and blocks<2 and reopen<1:return "SUPPRESS",text
 if _NO_OPPOSITE in text:
  text=_RECOMMEND_RE.sub("🧭 Рыночное направление: \\1",text)
  text=text.replace(_NO_OPPOSITE+" — не подставляю выдуманное значение.","⚠️ VALUE НЕ ПОДТВЕРЖДЁН: коэффициент противоположной стороны не получен. Это наблюдение за рынком, не готовая ставка.")
 label="CONFIRMED STEAM" if (blocks or 0)>=2 and (reopen or 0)>=1 else "STRONG MOVE"
 if f"🧠 Статус: {label}" not in text:text=text.replace(_TOP_MARKER,_TOP_MARKER+f"\n🧠 Статус: {label}",1)
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
