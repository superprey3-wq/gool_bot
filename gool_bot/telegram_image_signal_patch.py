"""Send actionable GOOL LIVE events as infographic PNG cards.

Entry cards are sent immediately. Goal-result cards are confirmed independently in a
small background verifier so a valid win cannot disappear merely because another patch
advanced TRACK before the next LIVE scan. The verifier re-reads the authoritative
Flashscore summary after a debounce window; a rollback/cancelled goal is never sent.
"""
from __future__ import annotations
import copy,logging,math,re,requests,threading,time
import live_candidate_patch as lc
import unified_bot
import gool_xg_consensus as gx
from live_engine import fetch_summary
from daily_report import _score_from_summary
from signal_card import render_signal_card
from telegram_subscribers import get_subscribers
from signal_card_archive import save_entry_card
logger=logging.getLogger("telegram_image_signal_patch")
_orig_send=lc._send
_GOAL_CANDIDATES={}
_GOAL_LOCK=threading.Lock()
GOAL_CONFIRM_MIN_SECONDS=40
GOAL_CONFIRM_RETRIES=3
GOAL_CONFIRM_RETRY_SECONDS=20

def _score_tuple(value):
    try:a,b=str(value).split(":",1);return int(a),int(b)
    except Exception:return 0,0

def _tracked_score(match):
    try:
        state=unified_bot._load_sent();row=state.get(f"TRACK:{match.event_id}") or {};return _score_tuple(row.get("score",f"{match.home_score}:{match.away_score}"))
    except Exception:return int(getattr(match,"home_score",0) or 0),int(getattr(match,"away_score",0) or 0)

def _display_probabilities(match,master,xg):
    minute=int(getattr(match,"minute",0) or 0);full_remaining=49.0 if getattr(match,"is_halftime",False) else max(0.0,94.0-minute);m=max(0.0,min(100.0,float(master or 0)));rate=(2.7/90.0)*(0.45+1.35*m/100.0);engine_lambda=max(0.0,rate*full_remaining);lam=engine_lambda;sources=int((xg or {}).get("sources",0) or 0);xg_lambda=float((xg or {}).get("lambda",0) or 0)
    if sources>=2 and xg_lambda>0:
        weight=0.35 if sources>=3 else 0.25;lam=engine_lambda*(1.0-weight)+xg_lambda*weight
    lam=max(0.0,min(5.0,lam));p1=(1.0-math.exp(-lam))*100.0;p2=(1.0-math.exp(-lam)*(1.0+lam))*100.0;first_half=None
    if minute<=45 and not getattr(match,"is_halftime",False) and full_remaining>0:
        fh_remaining=max(0.0,47.0-minute);fh_lam=lam*(fh_remaining/full_remaining);first_half=(1.0-math.exp(-fh_lam))*100.0
    return {"first_half_goal":None if first_half is None else round(first_half),"one_goal":round(p1),"two_goals":round(p2),"lambda":round(lam,3)}

def _compact_fallback(m,recs,kind,master,xg):
    if kind=="goal":return f"✅ <b>ЗАХОД!</b>\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"
    probs=_display_probabilities(m,master,xg);lines=["🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>","",f"⚽ <b>{m.home} — {m.away}</b>",f"⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"]
    if probs["first_half_goal"] is not None:lines.append(f"⏳ Гол до перерыва: <b>{probs['first_half_goal']}%</b>")
    lines.append(f"⚽ Ещё 1 гол до конца матча: <b>{probs['one_goal']}%</b>");lines.append(f"⚽⚽ Ещё 2 гола до конца матча: <b>{probs['two_goals']}%</b>");best=next((r for r in (recs or []) if r.get("best_bet")),None)
    if best:lines.append(f"💰 ТБ {float(best['line']):g} @ <b>{float(best['odd']):.2f}</b>")
    lines.append(f"🧠 Рейтинг: <b>{float(master or 0):.0f}/100</b>");return "\n".join(lines)

def _send_text_to_chat(token,chat_id,text):
    try:r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":str(chat_id),"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=20);return r.ok
    except requests.RequestException:return False

def _send_photo_all(match,pressure,recs,kind,master=None):
    token=unified_bot.BOT_TOKEN;recipients=get_subscribers()
    if not token or not recipients:return False
    xg=gx._cached(match) if kind=="entry" else None;probs=_display_probabilities(match,master,xg) if kind=="entry" else None
    try:png=render_signal_card(match,pressure,recs,kind=kind,master=master,probabilities=probs)
    except Exception as exc:logger.warning("GOOL image render failed: %s",exc);png=None
    caption="🔥 GOOL AI • МОЖНО ЗАХОДИТЬ" if kind=="entry" else "✅ GOOL AI • ЗАХОД!";fallback=_compact_fallback(match,recs,kind,master,xg);delivered=0;archived=False
    for chat_id in recipients:
        photo_ok=False
        if png:
            try:
                r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(chat_id),"caption":caption},files={"photo":("gool-signal.png",png,"image/png")},timeout=25);photo_ok=r.ok
                if photo_ok and kind=="entry" and not archived:
                    try:
                        photos=((r.json().get("result") or {}).get("photo") or []);file_id=(photos[-1] or {}).get("file_id") if photos else None
                        if file_id:save_entry_card(getattr(match,"event_id",""),file_id,caption);archived=True
                    except Exception as exc:logger.warning("Could not archive Telegram signal card: %s",exc)
                if not r.ok:logger.warning("GOOL image upload failed HTTP %s for %s: %s",r.status_code,chat_id,r.text[:160])
            except requests.RequestException as exc:logger.warning("GOOL image upload failed for %s: %s",chat_id,exc)
        if photo_ok:delivered+=1
        elif _send_text_to_chat(token,chat_id,fallback):delivered+=1
    logger.info("TELEGRAM_SIGNAL_DELIVERED %s %d/%d",kind,delivered,len(recipients));return delivered>0

def _close_confirmed_entry(event_id,score,minute):
    """Persist WIN and drop TRACK only after the green card was actually delivered."""
    try:
        from signal_journal_runtime_patch import mark_latest_entry_win
        mark_latest_entry_win(event_id,final_score=f"{score[0]}:{score[1]}",goal_minute=minute)
    except Exception:logger.exception("Could not mark confirmed WIN in journal for %s",event_id)
    try:
        state=unified_bot._load_sent();key=f"TRACK:{event_id}"
        if key in state:
            state.pop(key,None);unified_bot._save_sent(state)
            logger.info("GOAL_TRACK_CLOSED %s after confirmed green card",event_id)
    except Exception:logger.exception("Could not close TRACK after confirmed WIN for %s",event_id)

def _confirm_goal_worker(event_id):
    time.sleep(GOAL_CONFIRM_MIN_SECONDS)
    for attempt in range(GOAL_CONFIRM_RETRIES):
        with _GOAL_LOCK:candidate=_GOAL_CANDIDATES.get(event_id)
        if not candidate:return
        before=tuple(candidate["before"]);target=tuple(candidate["after"])
        try:
            body=fetch_summary(event_id)
            if not body:raise RuntimeError("empty summary")
            fh,fa,_,_=_score_from_summary(body);current=(int(fh),int(fa))
        except Exception as exc:
            logger.warning("GOAL_CONFIRM_FETCH_FAILED %s attempt=%d: %s",event_id,attempt+1,exc)
            if attempt+1<GOAL_CONFIRM_RETRIES:time.sleep(GOAL_CONFIRM_RETRY_SECONDS);continue
            with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
            return
        if sum(current)<sum(target):
            logger.warning("GOAL_CANCELLED %s before=%s candidate=%s current=%s",event_id,before,target,current)
            with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
            return
        # The score still contains the goal after the debounce window: it is safe to announce.
        m=copy.copy(candidate["match"]);m.home_score,m.away_score=current
        p=candidate["pressure"];recs=candidate["recs"];master=candidate["master"]
        delivered=_send_photo_all(m,p,recs,"goal",master)
        if delivered:
            logger.info("GOAL_CONFIRMED_ASYNC %s %s -> %s",event_id,before,current)
            _close_confirmed_entry(event_id,current,int(getattr(m,"minute",0) or 0))
        else:logger.error("GOAL_CONFIRMED_BUT_DELIVERY_FAILED %s",event_id)
        with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
        return

def _schedule_goal_confirmation(m,p,recs,master):
    event_id=str(getattr(m,"event_id","") or "");current=(int(getattr(m,"home_score",0) or 0),int(getattr(m,"away_score",0) or 0));previous=_tracked_score(m)
    if not event_id or sum(current)<=sum(previous):return False
    with _GOAL_LOCK:
        existing=_GOAL_CANDIDATES.get(event_id)
        if existing:
            # Keep the highest valid observed score while the verifier is waiting.
            if sum(current)>sum(tuple(existing.get("after") or (0,0))):existing["after"]=current;existing["match"]=copy.copy(m)
            return True
        _GOAL_CANDIDATES[event_id]={"before":previous,"after":current,"match":copy.copy(m),"pressure":p,"recs":list(recs or []),"master":master,"ts":time.time()}
    logger.info("GOAL_CONFIRM_SCHEDULED %s %s -> %s",event_id,previous,current)
    threading.Thread(target=_confirm_goal_worker,args=(event_id,),name=f"goal-confirm-{event_id}",daemon=True).start()
    return True

def _send(m,p,recs,text):
    if not text:return False
    kind="goal" if "СИГНАЛ ЗАШЁЛ" in text or "ГОЛ — СИГНАЛ СРАБОТАЛ" in text else "entry" if "МОЖНО ЗАХОДИТЬ" in text else None
    if not kind:return _orig_send(m,p,recs,text)
    master=None;mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text)
    if mm:
        try:master=float(mm.group(1))
        except ValueError:master=None
    if master is None:master=float(getattr(p,"score",0) or 0)
    if kind=="goal":
        # Do not rely on live_candidate_patch calling us again next scan. Schedule one
        # independent authoritative verification and let the core keep the old TRACK.
        _schedule_goal_confirmation(m,p,recs,master)
        return False
    if _send_photo_all(m,p,recs,"entry",master):logger.info("TELEGRAM_IMAGE_SENT entry %d' %s — %s",int(getattr(m,"minute",0) or 0),getattr(m,"home",""),getattr(m,"away",""));return True
    return False

lc._send=_send
