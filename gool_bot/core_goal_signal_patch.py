"""VAR-safe CORE goal confirmation for analytics-first signals.

A confirmed new goal closes the analytical signal as WIN. Signal quality is
measured by the football event itself and never by bookmaker odds. Delivery is
PNG-first; text is used only as a fallback if Telegram photo upload fails.
"""
from __future__ import annotations
import copy,logging,time,requests
from daily_report import _score_from_summary
from live_engine import fetch_summary
from signal_card import render_signal_card
from telegram_subscribers import get_subscribers
import telegram_image_signal_patch as tip

logger=logging.getLogger("core_goal_signal")

def _send_goal_card(event_id,row,candidate,current,minute):
 token=tip.unified_bot.BOT_TOKEN
 if not token:return False
 m=copy.copy(candidate.get("match"))
 if m is None:return False
 m.home_score,m.away_score=current
 m.minute=minute
 m.goal_minute=minute
 m.entry_score=str(row.get("score_at_signal") or '')
 p=candidate.get("pressure")
 recs=candidate.get("recs") or []
 master=candidate.get("master")
 try:png=render_signal_card(m,p,recs,kind="goal",master=master,probabilities=None)
 except Exception as exc:
  logger.exception("CORE_GOAL_SIGNAL_CARD_RENDER_FAILED %s: %s",event_id,exc);png=None
 before=m.entry_score or '?'
 text=(f"✅ <b>GOOL AI • СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ</b>\n\n"
       f"⚽ <b>{row.get('home')} — {row.get('away')}</b>\n"
       f"📈 <b>{before} → {current[0]}:{current[1]}</b>\n"
       f"⏱ гол после входа · {minute}'\n"
       f"<i>Прогноз модели по голевой активности подтверждён.</i>")
 delivered=0
 for cid in get_subscribers():
  ok=False
  if png:
   try:
    r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":f"✅ GOOL AI • ПОДТВЕРЖДЕНО • {before} → {current[0]}:{current[1]}"},files={"photo":("gool-core-goal.png",png,"image/png")},timeout=25)
    ok=bool(r.ok)
    if not ok:logger.warning("CORE_GOAL_SIGNAL_CARD_UPLOAD_FAILED chat=%s status=%s body=%s",cid,getattr(r,"status_code",None),str(getattr(r,"text",''))[:160])
   except requests.RequestException as exc:logger.warning("CORE_GOAL_SIGNAL_CARD_UPLOAD_FAILED chat=%s: %s",cid,exc)
  if not ok:ok=tip._send_text_to_chat(token,cid,text)
  delivered+=int(bool(ok))
 logger.info("CORE_GOAL_SIGNAL_CARD delivered=%d event=%s png=%s transition=%s->%s:%s",delivered,event_id,bool(png),before,current[0],current[1])
 return delivered>0

def _confirm_goal_worker(event_id):
 time.sleep(tip.GOAL_CONFIRM_MIN_SECONDS)
 for attempt in range(tip.GOAL_CONFIRM_RETRIES):
  with tip._GOAL_LOCK:candidate=tip._GOAL_CANDIDATES.get(event_id)
  if not candidate:return
  row=tip._pending_row(event_id)
  if not row:
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  target=tuple(candidate.get("after") or (0,0))
  try:
   body=fetch_summary(event_id)
   if not body:raise RuntimeError("empty summary")
   fh,fa,_,_=_score_from_summary(body);current=(int(fh),int(fa))
  except Exception as exc:
   logger.warning("SIGNAL_GOAL_CONFIRM_FETCH_FAILED %s attempt=%d: %s",event_id,attempt+1,exc)
   if attempt+1<tip.GOAL_CONFIRM_RETRIES:time.sleep(tip.GOAL_CONFIRM_RETRY_SECONDS);continue
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  if sum(current)<sum(target):
   with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
   return
  minute=int(candidate.get("goal_minute") or getattr(candidate.get("match"),"minute",0) or row.get("minute") or 0)
  try:
   from signal_journal_runtime_patch import mark_latest_entry_goal
   mark_latest_entry_goal(event_id,final_score=f"{current[0]}:{current[1]}",goal_minute=minute)
  except Exception:logger.exception("Could not mark analytical signal win %s",event_id)
  delivered=_send_goal_card(event_id,row,candidate,current,minute)
  if not delivered:logger.error("CORE_GOAL_CONFIRM_DELIVERY_FAILED event=%s score=%s:%s",event_id,current[0],current[1])
  try:tip._close_confirmed_entry(event_id,current,minute)
  except Exception:pass
  with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
  return

tip._confirm_goal_worker=_confirm_goal_worker
logger.info("CORE goal confirmation analytics-first | PNG transition card enabled")
