"""Replace actionable GOOL Telegram text with infographic PNG cards.

Analysis/tracking remains untouched. If image rendering/upload fails, fall back to
existing text delivery so a real signal is never lost.
"""
from __future__ import annotations
import logging,requests
import live_candidate_patch as lc
import unified_bot
import gool_xg_consensus as gx
from signal_card import render_signal_card
logger=logging.getLogger("telegram_image_signal_patch")
_orig_send=lc._send

def _send_photo(match,pressure,recs,kind,master=None):
    token,chat_id=unified_bot.BOT_TOKEN,unified_bot.CHAT_ID
    if not token or not chat_id:return False
    try:
        xg=gx._cached(match) if kind=="entry" else None
        png=render_signal_card(match,pressure,recs,kind=kind,master=master,xg=xg)
        r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":chat_id,"caption":"🔥 GOOL AI • LIVE" if kind=="entry" else "✅ GOOL AI • SIGNAL WON"},files={"photo":("gool-signal.png",png,"image/png")},timeout=25)
        if r.ok:return True
        logger.warning("GOOL image upload failed HTTP %s: %s",r.status_code,r.text[:160])
    except Exception as exc:logger.warning("GOOL image signal failed: %s",exc)
    return False

def _send(m,p,recs,text):
    if not text:return False
    kind="goal" if "СИГНАЛ ЗАШЁЛ" in text else "entry" if "МОЖНО ЗАХОДИТЬ" in text else None
    if kind:
        # Extract final rating already rendered into the filtered text when possible.
        master=None
        try:
            import re
            mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text)
            if mm:master=float(mm.group(1))
        except Exception:pass
        if _send_photo(m,p,recs,kind,master):
            logger.info("TELEGRAM_IMAGE_SENT %s %d' %s — %s",kind,int(getattr(m,"minute",0) or 0),getattr(m,"home",""),getattr(m,"away",""))
            return True
    # Safety fallback: never lose an actionable signal because Pillow/Telegram photo failed.
    return _orig_send(m,p,recs,text)

lc._send=_send
