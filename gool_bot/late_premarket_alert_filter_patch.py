"""Final smart outbound gate for TOP-load total alerts on the deploy branch.

This module must be imported LAST by the runtime. It protects the normal visual
sender plus direct requests.post, requests.Session.post and aiohttp
ClientSession.post Telegram sendMessage paths. Weak/late TOP-load alerts fail
closed before Telegram delivery.
"""
from __future__ import annotations
import logging, os, re
import requests
import aiohttp
import visual_feed_unified_bot as vf

logger=logging.getLogger("smart_topload_alert_filter")
_orig_send_text=vf._send_text
_orig_send_text_to_chat=vf._send_text_to_chat
_orig_requests_post=requests.post
_orig_session_post=requests.sessions.Session.post
_orig_aiohttp_post=aiohttp.ClientSession.post

_TOP_MARKER="ТОП-ПРОГРУЗ ТОТАЛА"
_LIVE_MINUTE_RE=re.compile(r"\bLIVE\s*·\s*(\d{1,3})'",re.IGNORECASE)
_BLOCK_RE=re.compile(r"Блокировок рынка:\s*(\d+)\s*·\s*reopen:\s*(\d+)",re.IGNORECASE)
_CHANGE_RE=re.compile(r"Изменение:\s*([+-]?\d+(?:[.,]\d+)?)\s*п\.п\.",re.IGNORECASE)
_NO_OPPOSITE="Кэф противоположной стороны не получен"
_RECOMMEND_RE=re.compile(r"^🎯\s*Рекомендованное направление:\s*(.+)$",re.MULTILINE)

MAX_LIVE_MINUTE=int(os.getenv("TOPLOAD_MAX_LIVE_MINUTE","80"))
LATE_LIVE_FROM=int(os.getenv("TOPLOAD_LATE_LIVE_FROM","70"))
MIN_BLOCKS=int(os.getenv("TOPLOAD_MIN_BLOCKS","3"))
MIN_REOPEN=int(os.getenv("TOPLOAD_MIN_REOPEN","2"))
MIN_MOVE_PP=float(os.getenv("TOPLOAD_MIN_MOVE_PP","7.0"))
LATE_MIN_BLOCKS=int(os.getenv("TOPLOAD_LATE_MIN_BLOCKS","4"))
LATE_MIN_REOPEN=int(os.getenv("TOPLOAD_LATE_MIN_REOPEN","3"))
LATE_MIN_MOVE_PP=float(os.getenv("TOPLOAD_LATE_MIN_MOVE_PP","10.0"))
STRONG_MOVE_PP=float(os.getenv("TOPLOAD_STRONG_MOVE_PP","10.0"))

class _SuppressedResponse:
 status_code=200
 ok=True
 status=200
 text='{"ok":true,"result":{"message_id":0}}'
 def json(self):return {"ok":True,"result":{"message_id":0}}

class _SuppressedAiohttpResponse:
 status=200
 async def text(self):return '{"ok":true,"result":{"message_id":0}}'
 async def json(self):return {"ok":True,"result":{"message_id":0}}

class _SuppressedAiohttpContext:
 async def __aenter__(self):return _SuppressedAiohttpResponse()
 async def __aexit__(self,exc_type,exc,tb):return False


def _decision(text):
 text=str(text or "")
 if _TOP_MARKER not in text:return "PASS",text
 m=_LIVE_MINUTE_RE.search(text);minute=int(m.group(1)) if m else None
 b=_BLOCK_RE.search(text);blocks=int(b.group(1)) if b else None;reopen=int(b.group(2)) if b else None
 c=_CHANGE_RE.search(text)
 try:move=float(c.group(1).replace(",",".")) if c else None
 except ValueError:move=None
 magnitude=abs(move) if move is not None else None

 if blocks is None or reopen is None or magnitude is None:
  logger.info("TOP_LOAD_SUPPRESS reason=missing_evidence blocks=%s reopen=%s move=%s",blocks,reopen,move);return "SUPPRESS",text
 if blocks<MIN_BLOCKS:
  logger.info("TOP_LOAD_SUPPRESS reason=blocks blocks=%d min=%d",blocks,MIN_BLOCKS);return "SUPPRESS",text
 if reopen<MIN_REOPEN:
  logger.info("TOP_LOAD_SUPPRESS reason=reopen reopen=%d min=%d",reopen,MIN_REOPEN);return "SUPPRESS",text
 if magnitude<MIN_MOVE_PP:
  logger.info("TOP_LOAD_SUPPRESS reason=weak_move move=%.2f min=%.2f",magnitude,MIN_MOVE_PP);return "SUPPRESS",text
 if minute is not None:
  if minute>MAX_LIVE_MINUTE:
   logger.info("TOP_LOAD_SUPPRESS reason=late_live minute=%d max=%d",minute,MAX_LIVE_MINUTE);return "SUPPRESS",text
  if minute>=LATE_LIVE_FROM and (blocks<LATE_MIN_BLOCKS or reopen<LATE_MIN_REOPEN or magnitude<LATE_MIN_MOVE_PP):
   logger.info("TOP_LOAD_SUPPRESS reason=late_weak minute=%d blocks=%d reopen=%d move=%.2f",minute,blocks,reopen,magnitude);return "SUPPRESS",text

 if _NO_OPPOSITE in text:
  text=_RECOMMEND_RE.sub("🧭 Рыночное направление: \\1",text)
  text=text.replace(_NO_OPPOSITE+" — не подставляю выдуманное значение.","⚠️ VALUE НЕ ПОДТВЕРЖДЁН: коэффициент противоположной стороны не получен. Это наблюдение за рынком, не готовая ставка.")
 label="CONFIRMED STEAM" if magnitude>=STRONG_MOVE_PP and blocks>=4 and reopen>=3 else "STRONG MOVE"
 if f"🧠 Статус: {label}" not in text:text=text.replace(_TOP_MARKER,_TOP_MARKER+f"\n🧠 Статус: {label}",1)
 return "PASS",text


def _guard_payload(kwargs):
 for key in ("json","data"):
  payload=kwargs.get(key)
  if isinstance(payload,dict) and isinstance(payload.get("text"),str) and _TOP_MARKER in payload["text"]:
   action,new_text=_decision(payload["text"])
   if action=="SUPPRESS":return False,kwargs
   payload=dict(payload);payload["text"]=new_text;kwargs=dict(kwargs);kwargs[key]=payload
 return True,kwargs


def _send_text(text):
 action,text=_decision(text)
 if action=="SUPPRESS":return False
 return _orig_send_text(text)


def _send_text_to_chat(token,chat_id,text):
 action,text=_decision(text)
 if action=="SUPPRESS":return False
 return _orig_send_text_to_chat(token,chat_id,text)


def _guarded_post(url,*args,**kwargs):
 if "api.telegram.org" in str(url) and "/sendMessage" in str(url):
  allowed,kwargs=_guard_payload(kwargs)
  if not allowed:
   logger.info("TOP_LOAD_HTTP_SUPPRESS requests.post")
   return _SuppressedResponse()
 return _orig_requests_post(url,*args,**kwargs)


def _guarded_session_post(self,url,*args,**kwargs):
 if "api.telegram.org" in str(url) and "/sendMessage" in str(url):
  allowed,kwargs=_guard_payload(kwargs)
  if not allowed:
   logger.info("TOP_LOAD_HTTP_SUPPRESS requests.Session.post")
   return _SuppressedResponse()
 return _orig_session_post(self,url,*args,**kwargs)


def _guarded_aiohttp_post(self,url,*args,**kwargs):
 if "api.telegram.org" in str(url) and "/sendMessage" in str(url):
  allowed,kwargs=_guard_payload(kwargs)
  if not allowed:
   logger.info("TOP_LOAD_HTTP_SUPPRESS aiohttp.ClientSession.post")
   return _SuppressedAiohttpContext()
 return _orig_aiohttp_post(self,url,*args,**kwargs)

vf._send_text=_send_text
vf._send_text_to_chat=_send_text_to_chat
requests.post=_guarded_post
requests.sessions.Session.post=_guarded_session_post
aiohttp.ClientSession.post=_guarded_aiohttp_post
logger.info("SMART_TOPLOAD_GATE FINAL enabled max_live=%d late_from=%d blocks=%d reopen=%d move=%.1f requests=on session=on aiohttp=on",MAX_LIVE_MINUTE,LATE_LIVE_FROM,MIN_BLOCKS,MIN_REOPEN,MIN_MOVE_PP)
