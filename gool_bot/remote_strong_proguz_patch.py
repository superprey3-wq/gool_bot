"""Main-bot Telegram relay for strong market flow from MonkeyBytes.

Strong PROGRUZ is a photo-card feature. Do not silently downgrade a card to text: if
rendering or Telegram sendPhoto fails, log the exact error and leave the signal unsent
so the next poll can retry it as a card.
"""
from __future__ import annotations
import json,logging,os,threading,time
from pathlib import Path
import requests
import unified_bot
from telegram_subscribers import get_subscribers
try:
 from strong_proguz_card import render as render_proguz_card
 CARD_IMPORT_ERROR=None
except Exception as exc:
 render_proguz_card=None;CARD_IMPORT_ERROR=f"{type(exc).__name__}:{exc}"
log=logging.getLogger("remote_strong_proguz")
URL=os.getenv("GOOL_STRONG_FEED_URL","http://eu.monkey-network.xyz:5056/strong");POLL=max(15,int(os.getenv("GOOL_STRONG_FEED_POLL","20")));MIN=float(os.getenv("GOOL_STRONG_FEED_MIN","80"));COOLDOWN=max(600,int(os.getenv("GOOL_STRONG_FEED_COOLDOWN","1800")));STATE=Path(os.getenv("GOOL_STRONG_FEED_SENT","strong_proguz_sent.json"))
def _load():
 try:d=json.loads(STATE.read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _save(d):
 cutoff=time.time()-86400;d={k:v for k,v in d.items() if float(v or 0)>=cutoff};tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(d),encoding="utf-8");tmp.replace(STATE)
def _period(scope):
 s=str(scope or "FULL_TIME").upper();return "1-Й ТАЙМ" if s=="FIRST_HALF" else "2-Й ТАЙМ" if s=="SECOND_HALF" else "ВЕСЬ МАТЧ"
def _side(side):
 s=str(side or "").upper();return "ТБ" if s=="OVER" else "ТМ" if s=="UNDER" else s
def _caption(x):
 line="" if x.get("line") in (None,"") else f" {x.get('line')}";odd=x.get("odd");odd_txt=f" @ {float(odd):.2f}" if isinstance(odd,(int,float)) else ""
 return f"🔥 <b>СИЛЬНЫЙ ПРОГРУЗ</b> • {_period(x.get('scope'))}\n📊 <b>{_side(x.get('side'))}{line}{odd_txt}</b> • 💪 {float(x.get('strength',0) or 0):.0f}/100"
def _send_card(x):
 token=unified_bot.BOT_TOKEN
 if not token:log.error("STRONG_PROGRUZ_CARD_DISABLED reason=no_bot_token");return 0
 if render_proguz_card is None:log.error("STRONG_PROGRUZ_CARD_DISABLED reason=import_failed err=%s",CARD_IMPORT_ERROR);return 0
 try:
  png=render_proguz_card(x)
  if not png:raise RuntimeError("renderer returned empty bytes")
 except Exception as exc:
  log.exception("STRONG_PROGRUZ_CARD_RENDER_FAILED event=%s err=%s",x.get("event_id"),exc);return 0
 n=0
 for cid in get_subscribers():
  try:
   r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":_caption(x),"parse_mode":"HTML"},files={"photo":("gool-strong-progruz.png",png,"image/png")},timeout=20)
   if r.ok:n+=1
   else:log.error("STRONG_PROGRUZ_CARD_TELEGRAM_FAILED event=%s chat=%s http=%s body=%s",x.get("event_id"),cid,r.status_code,(r.text or "")[:500])
  except requests.RequestException as exc:log.error("STRONG_PROGRUZ_CARD_HTTP_FAILED event=%s chat=%s err=%s",x.get("event_id"),cid,exc)
 return n
def poll_once():
 try:r=requests.get(URL,timeout=8);r.raise_for_status();rows=(r.json() or {}).get("strong") or []
 except Exception as exc:log.warning("STRONG_PROGRUZ_OFFLINE %s",exc);return 0
 sent=_load();now=time.time();n=0
 for x in rows:
  try:strength=float(x.get("strength",0) or 0)
  except Exception:continue
  if strength<MIN or int(x.get("books",0) or 0)<2:continue
  key=str(x.get("id") or "")
  if not key or now-float(sent.get(key,0) or 0)<COOLDOWN:continue
  delivered=_send_card(x)
  if delivered:
   sent[key]=now;n+=1;log.info("STRONG_PROGRUZ_CARD_SENT event=%s scope=%s side=%s score=%s minute=%s strength=%.1f books=%s recipients=%d",x.get("event_id"),x.get("scope"),x.get("side"),x.get("score_live"),x.get("minute"),strength,x.get("books"),delivered)
  else:log.error("STRONG_PROGRUZ_CARD_NOT_SENT event=%s will_retry=1",x.get("event_id"))
  if n>=3:break
 _save(sent);return n
def loop():
 log.info("REMOTE strong proguz relay CARD_ONLY_V2 url=%s min=%.0f renderer=%s",URL,MIN,"ok" if render_proguz_card else f"failed:{CARD_IMPORT_ERROR}")
 while True:poll_once();time.sleep(POLL)
threading.Thread(target=loop,name="strong-proguz-relay",daemon=True).start()
