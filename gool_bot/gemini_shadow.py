"""Non-blocking Gemini shadow reviewer for GOOL candidates.

Shadow mode never blocks, creates, or cancels Telegram signals. It only logs Gemini's
opinion and appends compact JSONL rows for later comparison with real outcomes.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger("gemini_shadow")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ENABLED = os.getenv("GEMINI_SHADOW_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
TIMEOUT_SECONDS = max(5, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "20")))
OUT_FILE = Path(os.getenv("GEMINI_SHADOW_FILE", "gemini_shadow.jsonl"))
_MAX_CONCURRENT = max(1, int(os.getenv("GEMINI_MAX_CONCURRENT", "2")))
_SEM = threading.BoundedSemaphore(_MAX_CONCURRENT)
_SEEN: set[str] = set()
_SEEN_LOCK = threading.Lock()
_SCHEMA = {"type":"OBJECT","properties":{"decision":{"type":"STRING","enum":["APPROVE","REJECT","CAUTION"]},"goal_probability":{"type":"INTEGER","minimum":1,"maximum":99},"confidence":{"type":"STRING","enum":["LOW","MEDIUM","HIGH"]},"reason":{"type":"STRING"},"risk":{"type":"STRING"}},"required":["decision","goal_probability","confidence","reason","risk"]}

def _pair(stats,key):
    try:a,b=stats.get(key,(0,0));return [float(a or 0),float(b or 0)]
    except Exception:return [0.0,0.0]

def _best_market(recs):
    row=next((r for r in list(recs or []) if r.get("best_bet")),None)
    if not row:return None
    try:return {"scope":row.get("scope"),"line":float(row.get("line")),"odd":float(row.get("odd")),"confidence":row.get("confidence"),"value_edge":row.get("value_edge")}
    except Exception:return None

def _prompt(payload):
    return "Ты независимый футбольный LIVE-аналитик внутри системы GOOL. Оцени только вероятность ЕЩЁ ОДНОГО гола после текущей точки входа. Не придумывай отсутствующие данные. Не доверяй рейтингу GOOL автоматически: используй минуту, счёт, статистику, давление, рынок и контекст. APPROVE = вход оправдан; CAUTION = погранично; REJECT = слабый/слишком рискованный. Верни только JSON по заданной схеме.\n\nДанные:\n"+json.dumps(payload,ensure_ascii=False)

def _extract_text(data):
    try:return "".join(str(p.get("text") or "") for p in data["candidates"][0]["content"]["parts"] if isinstance(p,dict)).strip()
    except Exception:return ""

def _append(row):
    try:
        with OUT_FILE.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False)+"\n")
    except Exception as exc:logger.warning("GEMINI_SHADOW_SAVE_FAILED: %s",exc)

def _review(payload,dedupe):
    if not _SEM.acquire(blocking=False):logger.info("GEMINI_SHADOW_SKIPPED busy %s",dedupe);return
    try:
        url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
        body={"contents":[{"role":"user","parts":[{"text":_prompt(payload)}]}],"generationConfig":{"temperature":0.1,"maxOutputTokens":300,"response_mime_type":"application/json","response_schema":_SCHEMA}}
        started=time.monotonic();r=requests.post(url,headers={"x-goog-api-key":API_KEY,"Content-Type":"application/json"},json=body,timeout=TIMEOUT_SECONDS);elapsed=round(time.monotonic()-started,2)
        if not r.ok:logger.warning("GEMINI_SHADOW_HTTP %s %s %s",r.status_code,dedupe,r.text[:240]);return
        text=_extract_text(r.json())
        if not text:logger.warning("GEMINI_SHADOW_EMPTY %s",dedupe);return
        try:verdict=json.loads(text)
        except Exception:logger.warning("GEMINI_SHADOW_BAD_JSON %s %s",dedupe,text[:240]);return
        row={"ts":int(time.time()),"model":MODEL,"event_id":payload.get("event_id"),"home":payload.get("home"),"away":payload.get("away"),"minute":payload.get("minute"),"score":payload.get("score"),"entry_type":payload.get("entry_type"),"gool_master":payload.get("master"),"gemini":verdict,"latency_s":elapsed};_append(row)
        logger.info("GEMINI_SHADOW %s %s — %s %s' %s | GOOL=%.0f | %s %s%% %s | risk=%s",payload.get("entry_type"),payload.get("home"),payload.get("away"),payload.get("minute"),payload.get("score"),float(payload.get("master") or 0),verdict.get("decision"),verdict.get("goal_probability"),verdict.get("confidence"),str(verdict.get("risk") or "")[:120])
    except requests.RequestException as exc:logger.warning("GEMINI_SHADOW_REQUEST_FAILED %s: %s",dedupe,exc)
    except Exception:logger.exception("GEMINI_SHADOW_FAILED %s",dedupe)
    finally:_SEM.release()

def submit(match,pressure,stats,recs,master,entry_type="signal"):
    if not ENABLED:return False
    if not API_KEY:logger.info("GEMINI_SHADOW_DISABLED no GEMINI_API_KEY");return False
    eid=str(getattr(match,"event_id","") or "");minute=int(getattr(match,"minute",0) or 0);score=f"{int(getattr(match,'home_score',0) or 0)}:{int(getattr(match,'away_score',0) or 0)}";dedupe=f"{eid}:{minute}:{score}:{entry_type}"
    with _SEEN_LOCK:
        if dedupe in _SEEN:return False
        _SEEN.add(dedupe)
        if len(_SEEN)>2000:_SEEN.clear();_SEEN.add(dedupe)
    payload={"event_id":eid,"home":str(getattr(match,"home","") or ""),"away":str(getattr(match,"away","") or ""),"league":str(getattr(match,"league","") or ""),"minute":minute,"score":score,"is_halftime":bool(getattr(match,"is_halftime",False)),"entry_type":entry_type,"master":round(float(master or 0),1),"pressure":round(float(getattr(pressure,"score",0) or 0),1),"momentum":round(float(getattr(pressure,"momentum",0) or 0),1),"xg":_pair(stats,"xg"),"shots":_pair(stats,"shots"),"shots_on_target":_pair(stats,"shots_on_target"),"big_chances":_pair(stats,"big_chances"),"corners":_pair(stats,"corners"),"shots_inside_box":_pair(stats,"shots_inside_box"),"touches_box":_pair(stats,"touches_box"),"best_market":_best_market(recs)}
    threading.Thread(target=_review,args=(payload,dedupe),name=f"gemini-shadow-{eid}",daemon=True).start();return True
