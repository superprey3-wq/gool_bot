"""Send actionable GOOL LIVE events as infographic PNG cards.

CORE result cards are market-aware: a new goal is only a trigger to re-check the selected
primary market. BTTS, team totals and match totals are announced as wins only when that
exact bet is fully won. VAR confirmation remains mandatory.
"""
from __future__ import annotations
import asyncio,copy,logging,math,re,requests,threading,time
import live_candidate_patch as lc
import unified_bot
import gool_xg_consensus as gx
from live_engine import fetch_summary
from daily_report import _score_from_summary
from signal_card import render_signal_card
from telegram_subscribers import get_subscribers
from signal_card_archive import save_entry_card
from signal_journal import all_signals
from market_settlement import fully_won_now
logger=logging.getLogger("telegram_image_signal_patch")
_orig_send=lc._send;_GOAL_CANDIDATES={};_GOAL_LOCK=threading.Lock();GOAL_CONFIRM_MIN_SECONDS=40;GOAL_CONFIRM_RETRIES=3;GOAL_CONFIRM_RETRY_SECONDS=20;ENTRY_REFRESH_RETRIES=2;ENTRY_REFRESH_RETRY_SECONDS=2;_PENDING_VALUES={"","pending","wait","waiting"}
def _score_tuple(value):
 try:a,b=str(value).split(":",1);return int(a),int(b)
 except:return 0,0
def _tracked_score(match):
 try:state=unified_bot._load_sent();row=state.get(f"TRACK:{match.event_id}") or {};return _score_tuple(row.get("score",f"{match.home_score}:{match.away_score}"))
 except Exception:return int(getattr(match,"home_score",0) or 0),int(getattr(match,"away_score",0) or 0)
def _pending_row(event_id):
 eid=str(event_id or "");best=None
 try:rows=all_signals()
 except Exception as exc:logger.warning("PENDING_ENTRY_CHECK_FAILED %s: %s",eid,exc);return None
 for r in rows:
  if r.get("kind")!="live" or str(r.get("event_id") or "")!=eid:continue
  if str(r.get("reason") or "signal") not in {"signal","reentry"}:continue
  if str(r.get("result") or "pending").strip().lower() not in _PENDING_VALUES:continue
  if best is None or int(r.get("created_ts",0) or 0)>=int(best.get("created_ts",0) or 0):best=r
 return best
def _has_pending_entry(event_id):return _pending_row(event_id) is not None
def _display_probabilities(match,master,xg):
 minute=int(getattr(match,"minute",0) or 0);full_remaining=49.0 if getattr(match,"is_halftime",False) else max(0.0,94.0-minute);m=max(0.0,min(100.0,float(master or 0)));rate=(2.7/90.0)*(0.45+1.35*m/100.0);engine_lambda=max(0.0,rate*full_remaining);lam=engine_lambda;sources=int((xg or {}).get("sources",0) or 0);xg_lambda=float((xg or {}).get("lambda",0) or 0)
 if sources>=2 and xg_lambda>0:weight=0.35 if sources>=3 else 0.25;lam=engine_lambda*(1.0-weight)+xg_lambda*weight
 lam=max(0.0,min(5.0,lam));p1=(1.0-math.exp(-lam))*100.;p2=(1.0-math.exp(-lam)*(1.0+lam))*100.;first_half=None
 if minute<=45 and not getattr(match,"is_halftime",False) and full_remaining>0:fh_remaining=max(0.,47.-minute);fh_lam=lam*(fh_remaining/full_remaining);first_half=(1.-math.exp(-fh_lam))*100.
 return {"first_half_goal":None if first_half is None else round(first_half),"one_goal":round(p1),"two_goals":round(p2),"lambda":round(lam,3)}
def _primary_label(primary):
 if not isinstance(primary,dict):return "ВЫБРАННАЯ СТАВКА"
 kind=str(primary.get("market_type") or primary.get("market") or "TOTAL_OVER").upper();line=primary.get("line");team=str(primary.get("team_name") or "КОМАНДЫ")
 if kind=="BTTS":return "ОБЕ ЗАБЬЮТ — ДА"
 if kind=="TEAM_TOTAL_HOME" or kind=="TEAM_TOTAL_AWAY":return f"ИТБ {team} {float(line):g}"
 if line is not None:return f"ТБ {float(line):g}"
 return kind
def _compact_fallback(m,recs,kind,master,xg):
 primary=(recs or [None])[0]
 if kind=="goal":return f"✅ <b>СТАВКА ЗАШЛА</b>\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>\n🎯 {_primary_label(primary)}"
 probs=_display_probabilities(m,master,xg);lines=["🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>","",f"⚽ <b>{m.home} — {m.away}</b>",f"⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>"];best=next((r for r in (recs or []) if r.get("best_concrete_bet")),None) or next((r for r in (recs or []) if r.get("best_bet")),None)
 if best:lines.append(f"⭐ <b>{_primary_label(best)}</b> @ <b>{float(best.get('odd',0)):.2f}</b>")
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
 primary=(recs or [None])[0];caption="🔥 GOOL AI • МОЖНО ЗАХОДИТЬ" if kind=="entry" else f"✅ GOOL AI • СТАВКА ЗАШЛА • {_primary_label(primary)}";fallback=_compact_fallback(match,recs,kind,master,xg);delivered=0;archived=False
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
   except requests.RequestException as exc:logger.warning("GOOL image upload failed for %s: %s",chat_id,exc)
  if photo_ok:delivered+=1
  elif _send_text_to_chat(token,chat_id,fallback):delivered+=1
 return delivered>0
def _close_confirmed_entry(event_id,score,minute):
 try:
  from signal_journal_runtime_patch import mark_latest_entry_win;mark_latest_entry_win(event_id,final_score=f"{score[0]}:{score[1]}",goal_minute=minute)
 except Exception:logger.exception("Could not settle confirmed primary for %s",event_id)
 try:
  state=unified_bot._load_sent();key=f"TRACK:{event_id}"
  if key in state:state.pop(key,None);unified_bot._save_sent(state)
 except Exception:logger.exception("Could not close TRACK for %s",event_id)
def _fresh_live_match(event_id):
 box={}
 def worker():
  try:matches=asyncio.run(unified_bot.discover_live_matches());box["match"]=next((x for x in matches if str(getattr(x,"event_id",""))==str(event_id)),None)
  except Exception as exc:box["error"]=exc
 t=threading.Thread(target=worker,daemon=True);t.start();t.join(12)
 return None if t.is_alive() or box.get("error") else box.get("match")
def _sync_entry_match(match):
 fresh=None
 for attempt in range(ENTRY_REFRESH_RETRIES):
  fresh=_fresh_live_match(str(getattr(match,"event_id","") or ""))
  if fresh is not None:break
  if attempt+1<ENTRY_REFRESH_RETRIES:time.sleep(ENTRY_REFRESH_RETRY_SECONDS)
 if fresh is None:return None
 synced=copy.copy(match);synced.minute=int(getattr(fresh,"minute",0) or 0);synced.home_score=int(getattr(fresh,"home_score",0) or 0);synced.away_score=int(getattr(fresh,"away_score",0) or 0);synced.is_halftime=bool(getattr(fresh,"is_halftime",False));return synced
def _confirm_goal_worker(event_id):
 time.sleep(GOAL_CONFIRM_MIN_SECONDS)
 for attempt in range(GOAL_CONFIRM_RETRIES):
  with _GOAL_LOCK:candidate=_GOAL_CANDIDATES.get(event_id)
  if not candidate:return
  row=_pending_row(event_id)
  if not row:
   with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
   return
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
   with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
   return
  primary=row.get("primary")
  # Critical: a goal is NOT automatically a win. Re-check the exact selected market.
  if not fully_won_now(primary,f"{current[0]}:{current[1]}"):
   logger.info("PRIMARY_NOT_WON_YET %s market=%s score=%s",event_id,_primary_label(primary),current)
   with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
   return
  fresh=_fresh_live_match(event_id);m=copy.copy(fresh or candidate["match"]);m.home_score,m.away_score=current;p=candidate["pressure"];master=candidate["master"];recs=[copy.deepcopy(primary)] if isinstance(primary,dict) else candidate["recs"]
  if not _has_pending_entry(event_id):
   with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
   return
  delivered=_send_photo_all(m,p,recs,"goal",master)
  if delivered:_close_confirmed_entry(event_id,current,int(getattr(m,"minute",0) or 0))
  with _GOAL_LOCK:_GOAL_CANDIDATES.pop(event_id,None)
  return
def _schedule_goal_confirmation(m,p,recs,master):
 event_id=str(getattr(m,"event_id","") or "");row=_pending_row(event_id)
 if not event_id or not row:return False
 current=(int(getattr(m,"home_score",0) or 0),int(getattr(m,"away_score",0) or 0));previous=_tracked_score(m)
 if sum(current)<=sum(previous):return False
 with _GOAL_LOCK:
  existing=_GOAL_CANDIDATES.get(event_id)
  if existing:
   if sum(current)>sum(tuple(existing.get("after") or (0,0))):existing["after"]=current;existing["match"]=copy.copy(m)
   return True
  _GOAL_CANDIDATES[event_id]={"before":previous,"after":current,"match":copy.copy(m),"pressure":p,"recs":list(recs or []),"master":master,"ts":time.time()}
 threading.Thread(target=_confirm_goal_worker,args=(event_id,),daemon=True).start();return True
def _send(m,p,recs,text):
 if not text:return False
 kind="goal" if "СИГНАЛ ЗАШЁЛ" in text or "ГОЛ — СИГНАЛ СРАБОТАЛ" in text else "entry" if "МОЖНО ЗАХОДИТЬ" in text else None
 if not kind:return _orig_send(m,p,recs,text)
 master=None;mm=re.search(r"Рейтинг сигнала:\s*<b>([0-9.]+)/100",text)
 if mm:
  try:master=float(mm.group(1))
  except ValueError:pass
 if master is None:master=float(getattr(p,"score",0) or 0)
 if kind=="goal":_schedule_goal_confirmation(m,p,recs,master);return False
 synced=_sync_entry_match(m)
 if synced is None:return False
 return bool(_send_photo_all(synced,p,recs,"entry",master))
lc._send=_send
