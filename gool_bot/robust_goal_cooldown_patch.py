"""Robust post-goal cooldown shared by GOOL CORE.

Flashscore goal timelines can lag by one scan, while the score may update immediately.
This patch records a cooldown marker as soon as a score increase is detected by the
Telegram goal-confirmation path, then blocks CORE entry qualification for at least five
wall-clock minutes and five match minutes. This prevents an immediate fresh signal after
a goal even if TRACK is closed asynchronously before the timeline catches up.
"""
from __future__ import annotations
import json,time,logging
from pathlib import Path
import live_candidate_patch as lc
import telegram_image_signal_patch as tip

logger=logging.getLogger("robust_goal_cooldown")
STORE=Path(__file__).with_name("goal_cooldowns.json")
COOLDOWN_SECONDS=5*60
COOLDOWN_MATCH_MINUTES=5


def _load():
    try:
        data=json.loads(STORE.read_text("utf-8"))
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}


def _save(data):
    cutoff=time.time()-12*3600
    clean={k:v for k,v in data.items() if float((v or {}).get("ts",0) or 0)>=cutoff}
    try:STORE.write_text(json.dumps(clean,ensure_ascii=False,indent=2),"utf-8")
    except Exception as exc:logger.warning("GOAL_COOLDOWN_SAVE_FAILED %s",exc)


def mark(event_id,minute,score=None):
    eid=str(event_id or "")
    if not eid:return
    data=_load();data[eid]={"ts":time.time(),"minute":int(minute or 0),"score":score or ""};_save(data)
    logger.info("GOAL_COOLDOWN_MARKED %s minute=%s score=%s",eid,minute,score)


def active(event_id,current_minute):
    row=_load().get(str(event_id or ""))
    if not row:return False
    age=time.time()-float(row.get("ts",0) or 0)
    try:match_delta=int(current_minute or 0)-int(row.get("minute",0) or 0)
    except Exception:match_delta=0
    # Require BOTH five real minutes and five match minutes before CORE may re-enter.
    return age<COOLDOWN_SECONDS or match_delta<COOLDOWN_MATCH_MINUTES


# Mark immediately when a changed score schedules goal confirmation. This is earlier than
# confirmed delivery and therefore closes the one-scan race that used to create a new entry.
_orig_schedule=tip._schedule_goal_confirmation
def _schedule(m,p,recs,master):
    try:
        current=(int(getattr(m,"home_score",0) or 0),int(getattr(m,"away_score",0) or 0))
        previous=tip._tracked_score(m)
        if sum(current)>sum(previous):mark(getattr(m,"event_id",""),getattr(m,"minute",0),f"{current[0]}:{current[1]}")
    except Exception:logger.exception("GOAL_COOLDOWN_MARK_FAILED")
    return _orig_schedule(m,p,recs,master)
tip._schedule_goal_confirmation=_schedule


# Keep the existing warmup/timeline checks and add our persistent score-change marker.
_orig_evaluate=lc._evaluate
def _evaluate(m,s,p,goals,market):
    result=_orig_evaluate(m,s,p,goals,market)
    if not active(getattr(m,"event_id",""),getattr(m,"minute",0)):return result
    qualifies,route,master,sc,hz,mkt=result
    return False,"ROBUST_POST_GOAL_5M",master,sc,hz,mkt
lc._evaluate=_evaluate
