"""VAR-safe CORE goal confirmation against the exact journal entry score.

A signal is a WIN only when the confirmed score has increased after that
specific entry. Confirmations are delivered as PNG result cards; text is only a
fallback if rendering or Telegram photo upload fails.
"""
from __future__ import annotations
import copy,time,logging,threading,requests
from daily_report import _score_from_summary
from live_engine import fetch_summary
from telegram_subscribers import get_subscribers
import telegram_image_signal_patch as tip

logger=logging.getLogger("core_goal_signal")


def _score(value):
 try:a,b=str(value or "0:0").split(":",1);return int(a),int(b)
 except Exception:return 0,0


def _advanced(current,before):
 return int(current[0])>int(before[0]) or int(current[1])>int(before[1])


def _schedule_goal_confirmation(match,pressure,recs,master):
 event_id=str(getattr(match,"event_id","") or "")
 row=tip._pending_row(event_id)
 if not event_id or not row:return False
 before=_score(row.get("score_at_signal"));current=(int(getattr(match,"home_score",0) or 0),int(getattr(match,"away_score",0) or 0))
 if not _advanced(current,before):
  logger.info("GOAL_CANDIDATE_REJECT_NO_POST_ENTRY_GOAL %s entry=%s current=%s",event_id,before,current);return False
 with tip._GOAL_LOCK:
  existing=tip._GOAL_CANDIDATES.get(event_id)
  if existing:
   old_before=tuple(existing.get("before") or before)
   if tuple(before)!=tuple(old_before):tip._GOAL_CANDIDATES.pop(event_id,None)
   else:
    if sum(current)>sum(tuple(existing.get("after") or (0,0))):existing["after"]=current;existing["match"]=copy.copy(match)
    return True
  tip._GOAL_CANDIDATES[event_id]={"before":before,"after":current,"match":copy.copy(match),"pressure":pressure,"recs":list(recs or []),"master":master,"ts":time.time(),"entry_key":str(row.get("dedupe_key") or "")}
 threading.Thread(target=_confirm_goal_worker,args=(event_id,),daemon=True).start();return True


def _send_result_card(row,candidate,current,minute):
 token=tip.unified_bot.BOT_TOKEN
 if not token:return False
 m=copy.copy(candidate.get("match"));m.home_score,m.away_score=current;m.minute=minute
 p=candidate.get("pressure");recs=candidate.get("recs") or [];master=candidate.get("master")
 try:
  png=tip.render_signal_card(m,p,recs,kind="goal",master=master,probabilities=None)
  logger.info("CORE_RESULT_CARD_RENDER_OK %s bytes=%d",row.get("event_id"),len(png or b""))
 except Exception as exc:
  logger.exception("CORE_RESULT_CARD_RENDER_FAIL %s: %s",row.get("event_id"),exc);png=None
 caption="✅ GOOL AI • СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ"
 fallback=(f"✅ <b>GOOL AI • СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ</b>\n\n"
           f"⚽ <b>{row.get('home')} — {row.get('away')}</b>\n"
           f"⏱ после сигнала · <b>{current[0]}:{current[1]}</b>\n"
           f"<i>Счёт в момент входа: {row.get('score_at_signal')}. Новый гол после входа подтверждён.</i>")
 ok=0
 for cid in get_subscribers():
  photo_ok=False
  if png:
   try:
    r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":caption},files={"photo":("gool-result.png",png,"image/png")},timeout=25)
    photo_ok=r.ok
    if not r.ok:logger.warning("CORE_RESULT_CARD_UPLOAD_FAIL %s chat=%s HTTP=%s %s",row.get("event_id"),cid,r.status_code,r.text[:200])
   except requests.RequestException as exc:logger.warning("CORE_RESULT_CARD_UPLOAD_FAIL %s chat=%s %s",row.get("event_id"),cid,exc)
  if photo_ok:ok+=1
  elif tip._send_text_to_chat(token,cid,fallback):
   ok+=1;logger.warning("CORE_RESULT_TEXT_FALLBACK %s chat=%s",row.get("event_id"),cid)
 return ok>0


def _confirm_goal_worker(event_id):
 time.sleep(tip.GOAL_CONFIRM_MIN_SECONDS)
 for attempt in range(tip.GOAL_CONFIRM_RETRIES):
  with tip._GOAL_LOCK:candidate=tip._GOAL_CANDIDATES.get(event_id)
  if not candidate:return
  row=tip._pending_row(event_id)
  if not row:
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  if candidate.get("entry_key") and str(row.get("dedupe_key") or "")!=str(candidate.get("entry_key")):
   logger.info("GOAL_CANDIDATE_STALE_ENTRY %s old=%s new=%s",event_id,candidate.get("entry_key"),row.get("dedupe_key"));
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  before=_score(row.get("score_at_signal"))
  try:
   body=fetch_summary(event_id)
   if not body:raise RuntimeError("empty summary")
   fh,fa,_,_=_score_from_summary(body);current=(int(fh),int(fa))
  except Exception as exc:
   logger.warning("SIGNAL_GOAL_CONFIRM_FETCH_FAILED %s attempt=%d: %s",event_id,attempt+1,exc)
   if attempt+1<tip.GOAL_CONFIRM_RETRIES:time.sleep(tip.GOAL_CONFIRM_RETRY_SECONDS);continue
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  if not _advanced(current,before):
   logger.info("GOAL_CONFIRM_REJECT_SAME_SCORE %s entry=%s confirmed=%s",event_id,before,current)
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  minute=int(getattr(candidate.get("match"),"minute",0) or row.get("minute") or 0)
  try:
   from signal_journal_runtime_patch import mark_latest_entry_goal
   if not mark_latest_entry_goal(event_id,final_score=f"{current[0]}:{current[1]}",goal_minute=minute):raise RuntimeError("journal entry was not settled")
  except Exception:
   logger.exception("Could not mark analytical signal win %s",event_id)
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  _send_result_card(row,candidate,current,minute)
  try:tip._close_confirmed_entry(event_id,current,minute)
  except Exception:pass
  with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
  return

tip._schedule_goal_confirmation=_schedule_goal_confirmation
tip._confirm_goal_worker=_confirm_goal_worker
logger.info("CORE goal confirmation: exact journal baseline + PNG result card + post-confirm cooldown")
