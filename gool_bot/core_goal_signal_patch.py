"""VAR-safe CORE goal confirmation for analytics-first signals.

A confirmed new goal closes the analytical signal as WIN regardless of whether
the optional displayed bet has crossed yet. Bet settlement is stored separately.
"""
from __future__ import annotations
import time,logging
from daily_report import _score_from_summary
from live_engine import fetch_summary
from telegram_subscribers import get_subscribers
import telegram_image_signal_patch as tip

logger=logging.getLogger("core_goal_signal")

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
  minute=int(getattr(candidate.get("match"),"minute",0) or row.get("minute") or 0)
  try:
   from signal_journal_runtime_patch import mark_latest_entry_goal
   mark_latest_entry_goal(event_id,final_score=f"{current[0]}:{current[1]}",goal_minute=minute)
  except Exception:logger.exception("Could not mark analytical signal win %s",event_id)
  token=tip.unified_bot.BOT_TOKEN
  if token:
   text=f"✅ <b>GOOL AI • СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ</b>\n\n⚽ <b>{row.get('home')} — {row.get('away')}</b>\n⏱ после входа · <b>{current[0]}:{current[1]}</b>\n<i>Коэффициент/ставка на карточке — отдельная справочная метрика.</i>"
   for cid in get_subscribers():tip._send_text_to_chat(token,cid,text)
  try:tip._close_confirmed_entry(event_id,current,minute)
  except Exception:pass
  with tip._GOAL_LOCK:tip._GOAL_CANDIDATES.pop(event_id,None)
  return

tip._confirm_goal_worker=_confirm_goal_worker
logger.info("CORE goal confirmation is signal-first; card bet cannot delay WIN")
