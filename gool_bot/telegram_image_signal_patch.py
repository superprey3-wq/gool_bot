"""Send actionable GOOL LIVE events as compact infographic PNG cards.

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
logger=logging.getLogger("telegram_image_signal_patch")
_orig_send=lc._send

def _display_probabilities(match,master,xg):
    """Return coherent P(>=1), P(>=2) and first-half P(>=1) from one lambda.

    Main GOOL hazard supplies most of the expectation. XG consensus only calibrates
    it when at least two secondary sources are available.
    """
    minute=int(getattr(match,"minute",0) or 0)
    if getattr(match,"is_halftime",False):full_remaining=49.0
    else:full_remaining=max(0.0,94.0-minute)
    m=max(0.0,min(100.0,float(master or 0)))
    rate=(2.7/90.0)*(0.45+1.35*m/100.0)
    engine_lambda=max(0.0,rate*full_remaining)
    lam=engine_lambda
    sources=int((xg or {}).get("sources",0) or 0)
    xg_lambda=float((xg or {}).get("lambda",0) or 0)
    if sources>=2 and xg_lambda>0:
        weight=0.35 if sources>=3 else 0.25
        lam=engine_lambda*(1.0-weight)+xg_lambda*weight
    lam=max(0.0,min(5.0,lam))
    p1=(1.0-math.exp(-lam))*100.0
    p2=(1.0-math.exp(-lam)*(1.0+lam))*100.0
    first_half=None
    if minute<=45 and not getattr(match,"is_halftime",False) and full_remaining>0:
        fh_remaining=max(0.0,47.0-minute)
        fh_lam=lam*(fh_remaining/full_remaining)
        first_half=(1.0-math.exp(-fh_lam))*100.0
    return {"first_half_goal":None if first_half is None else round(first_half),"one_goal":round(p1),"two_goals":round(p2),"lambda":round(lam,3)}

def _send_photo(match,pressure,recs,kind,master=None):
    token,chat_id=unified_bot.BOT_TOKEN,unified_bot.CHAT_ID
    if not token or not chat_id:return False
    try:
        xg=gx._cached(match) if kind=="entry" else None
        probs=_display_probabilities(match,master,xg) if kind=="entry" else None
        png=render_signal_card(match,pressure,recs,kind=kind,master=master,probabilities=probs)
        caption="🔥 GOOL AI • МОЖНО ЗАХОДИТЬ" if kind=="entry" else "✅ GOOL AI • СИГНАЛ ЗАШЁЛ"
        r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":chat_id,"caption":caption},files={"photo":("gool-signal.png",png,"image/png")},timeout=25)
        if r.ok:return True
        logger.warning("GOOL image upload failed HTTP %s: %s",r.status_code,r.text[:160])
    except Exception as exc:logger.warning("GOOL image signal failed: %s",exc)
    return False

def _compact_fallback(m,recs,kind,master,xg):
    if kind=="goal":
        return f"✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"
    probs=_display_probabilities(m,master,xg)
    lines=["🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>","",f"⚽ <b>{m.home} — {m.away}</b>",f"⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"]
    if probs["first_half_goal"] is not None:lines.append(f"⏳ Гол до перерыва: <b>{probs['first_half_goal']}%</b>")
    lines.append(f"⚽ Ещё 1 гол до конца матча: <b>{probs['one_goal']}%</b>")
    lines.append(f"⚽⚽ Ещё 2 гола до конца матча: <b>{probs['two_goals']}%</b>")
    best=next((r for r in (recs or []) if r.get("best_bet")),None)
    if best:lines.append(f"💰 ТБ {float(best['line']):g} @ <b>{float(best['odd']):.2f}</b>")
    lines.append(f"🧠 Рейтинг: <b>{float(master or 0):.0f}/100</b>")
    return "\n".join(lines)

def _send(m,p,recs,text):
    if not text:return False
    kind="goal" if "СИГНАЛ ЗАШЁЛ" in text else "entry" if "МОЖНО ЗАХОДИТЬ" in text else None
    if not kind:return _orig_send(m,p,recs,text)
    master=None
    mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text)
    if mm:
        try:master=float(mm.group(1))
        except ValueError:master=None
    if master is None:master=float(getattr(p,"score",0) or 0)
    if _send_photo(m,p,recs,kind,master):
        logger.info("TELEGRAM_IMAGE_SENT %s %d' %s — %s",kind,int(getattr(m,"minute",0) or 0),getattr(m,"home",""),getattr(m,"away",""))
        return True
    xg=gx._cached(m) if kind=="entry" else None
    return _orig_send(m,p,recs,_compact_fallback(m,recs,kind,master,xg))

lc._send=_send
