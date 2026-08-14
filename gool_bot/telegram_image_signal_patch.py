"""Send actionable GOOL LIVE events as compact infographic PNG cards to all subscribers.

The analytical engine remains unchanged. User-facing probabilities are derived from
one display model so Telegram never shows conflicting percentages. The established
GOOL master remains primary; XG consensus is only a secondary calibration input.
"""
from __future__ import annotations
import logging,math,re,requests
import live_candidate_patch as lc
import unified_bot
import gool_xg_consensus as gx
from signal_card import render_signal_card
from telegram_subscribers import get_subscribers
logger=logging.getLogger("telegram_image_signal_patch")
_orig_send=lc._send

def _display_probabilities(match,master,xg):
    minute=int(getattr(match,"minute",0) or 0)
    if getattr(match,"is_halftime",False):full_remaining=49.0
    else:full_remaining=max(0.0,94.0-minute)
    m=max(0.0,min(100.0,float(master or 0)))
    rate=(2.7/90.0)*(0.45+1.35*m/100.0)
    engine_lambda=max(0.0,rate*full_remaining);lam=engine_lambda
    sources=int((xg or {}).get("sources",0) or 0);xg_lambda=float((xg or {}).get("lambda",0) or 0)
    if sources>=2 and xg_lambda>0:
        weight=0.35 if sources>=3 else 0.25;lam=engine_lambda*(1.0-weight)+xg_lambda*weight
    lam=max(0.0,min(5.0,lam));p1=(1.0-math.exp(-lam))*100.0;p2=(1.0-math.exp(-lam)*(1.0+lam))*100.0
    first_half=None
    if minute<=45 and not getattr(match,"is_halftime",False) and full_remaining>0:
        fh_remaining=max(0.0,47.0-minute);fh_lam=lam*(fh_remaining/full_remaining);first_half=(1.0-math.exp(-fh_lam))*100.0
    return {"first_half_goal":None if first_half is None else round(first_half),"one_goal":round(p1),"two_goals":round(p2),"lambda":round(lam,3)}

def _compact_fallback(m,recs,kind,master,xg):
    if kind=="goal":return f"✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"
    probs=_display_probabilities(m,master,xg);lines=["🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>","",f"⚽ <b>{m.home} — {m.away}</b>",f"⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"]
    if probs["first_half_goal"] is not None:lines.append(f"⏳ Гол до перерыва: <b>{probs['first_half_goal']}%</b>")
    lines.append(f"⚽ Ещё 1 гол до конца матча: <b>{probs['one_goal']}%</b>");lines.append(f"⚽⚽ Ещё 2 гола до конца матча: <b>{probs['two_goals']}%</b>")
    best=next((r for r in (recs or []) if r.get("best_bet")),None)
    if best:lines.append(f"💰 ТБ {float(best['line']):g} @ <b>{float(best['odd']):.2f}</b>")
    lines.append(f"🧠 Рейтинг: <b>{float(master or 0):.0f}/100</b>");return "\n".join(lines)

def _send_text_to_chat(token,chat_id,text):
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":str(chat_id),"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=20)
        return r.ok
    except requests.RequestException:return False

def _send_photo_all(match,pressure,recs,kind,master=None):
    token=unified_bot.BOT_TOKEN
    recipients=get_subscribers()
    if not token or not recipients:return False
    xg=gx._cached(match) if kind=="entry" else None
    probs=_display_probabilities(match,master,xg) if kind=="entry" else None
    try:png=render_signal_card(match,pressure,recs,kind=kind,master=master,probabilities=probs)
    except Exception as exc:
        logger.warning("GOOL image render failed: %s",exc);png=None
    caption="🔥 GOOL AI • МОЖНО ЗАХОДИТЬ" if kind=="entry" else "✅ GOOL AI • СИГНАЛ ЗАШЁЛ"
    fallback=_compact_fallback(match,recs,kind,master,xg)
    delivered=0
    for chat_id in recipients:
        photo_ok=False
        if png:
            try:
                r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(chat_id),"caption":caption},files={"photo":("gool-signal.png",png,"image/png")},timeout=25)
                photo_ok=r.ok
                if not r.ok:logger.warning("GOOL image upload failed HTTP %s for %s: %s",r.status_code,chat_id,r.text[:160])
            except requests.RequestException as exc:logger.warning("GOOL image upload failed for %s: %s",chat_id,exc)
        if photo_ok:delivered+=1
        elif _send_text_to_chat(token,chat_id,fallback):delivered+=1
    logger.info("TELEGRAM_SIGNAL_DELIVERED %s %d/%d",kind,delivered,len(recipients))
    return delivered>0

def _send(m,p,recs,text):
    if not text:return False
    kind="goal" if "СИГНАЛ ЗАШЁЛ" in text else "entry" if "МОЖНО ЗАХОДИТЬ" in text else None
    if not kind:return _orig_send(m,p,recs,text)
    master=None;mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text)
    if mm:
        try:master=float(mm.group(1))
        except ValueError:master=None
    if master is None:master=float(getattr(p,"score",0) or 0)
    if _send_photo_all(m,p,recs,kind,master):
        logger.info("TELEGRAM_IMAGE_SENT %s %d' %s — %s",kind,int(getattr(m,"minute",0) or 0),getattr(m,"home",""),getattr(m,"away",""));return True
    return False

lc._send=_send
