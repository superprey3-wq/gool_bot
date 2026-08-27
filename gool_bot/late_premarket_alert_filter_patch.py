"""Final outbound guard for stale TOP-load total alerts.

These market-movement alerts are not actionable at 90+ minutes.  Suppress them
before Telegram delivery even if an older/optional producer still creates the text.
"""
from __future__ import annotations
import logging
import re
import visual_feed_unified_bot as vf

logger=logging.getLogger("late_premarket_alert_filter")

_orig_send_text=vf._send_text
_orig_send_text_to_chat=vf._send_text_to_chat

_TOP_MARKER="ТОП-ПРОГРУЗ ТОТАЛА"
_LIVE_MINUTE_RE=re.compile(r"\bLIVE\s*·\s*(\d{1,3})'",re.IGNORECASE)


def _blocked(text):
    text=str(text or "")
    if _TOP_MARKER not in text:return False
    m=_LIVE_MINUTE_RE.search(text)
    if not m:return False
    minute=int(m.group(1))
    if minute>=90:
        logger.info("TOP_LOAD_LATE_SUPPRESS minute=%d",minute)
        return True
    return False


def _send_text(text):
    if _blocked(text):return False
    return _orig_send_text(text)


def _send_text_to_chat(token,chat_id,text):
    if _blocked(text):return False
    return _orig_send_text_to_chat(token,chat_id,text)


vf._send_text=_send_text
vf._send_text_to_chat=_send_text_to_chat
