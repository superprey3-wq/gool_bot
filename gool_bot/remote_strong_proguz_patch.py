"""Main-bot Telegram relay for strong market flow from MonkeyBytes."""
from __future__ import annotations
import json, logging, os, threading, time
from pathlib import Path
import requests
import unified_bot
from telegram_subscribers import get_subscribers
from strong_proguz_card import render as render_proguz_card

log=logging.getLogger("remote_strong_proguz")
URL=os.getenv("GOOL_STRONG_FEED_URL","http://eu.monkey-network.xyz:5056/strong")
POLL=max(15,int(os.getenv("GOOL_STRONG_FEED_POLL","20")))
MIN=float(os.getenv("GOOL_STRONG_FEED_MIN","80")); COOLDOWN=max(600,int(os.getenv("GOOL_STRONG_FEED_COOLDOWN","1800")))
STATE=Path(os.getenv("GOOL_STRONG_FEED_SENT","strong_proguz_sent.json"))

def _load():
 try:
  d=json.loads(STATE.read_text(encoding="utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _save(d):
 cutoff=time.time()-86400;d={k:v for k,v in d.items() if float(v or 0)>=cutoff};tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(d),encoding="utf-8");tmp.replace(STATE)
def _period(scope):
 s=str(scope or "FULL_TIME").upper()
 if s=="FIRST_HALF":return "1-Й ТАЙМ"
 if s=="SECOND_HALF":return "2-Й ТАЙМ"
 return "ВЕСЬ МАТЧ"
def _side(side):
 s=str(side or "").upper();return "ТБ" if s=="OVER" else "ТМ" if s=="UNDER" else s
def _caption(x):
 line="" if x.get("line") in (None,"") else f" {x.get('line')}";odd=x.get("odd");odd_txt=f" @ {float(odd):.2f}" if isinstance(odd,(int,float)) else ""
 return (f"🔥 <b>СИЛЬНЫЙ ПРОГРУЗ</b> • {_period(x.get('scope'))}\n"
         f"📊 <b>{_side(x.get('side'))}{line}{odd_txt}</b> • 💪 {float(x.get('strength',0) or 0):.0f}/100")
def _fmt(x):
 score=str(x.get("score_live") or x.get("score") or "").strip();minute=x.get("minute");line="" if x.get("line") in (None,"") else f" {x.get('line')}";odd=x.get("odd");odd_txt=f" @ {float(odd):.2f}" if isinstance(odd,(int,float)) else ""
 live=(f"⚽ Счёт <b>{score}</b> | Минута <b>{minute}'</b>\n" if score and minute not in (None,"") else "")
 return ("🔥 <b>СИЛЬНЫЙ ПРОГРУЗ</b>\n\n"f"⚽ <b>{x.get('home','')} — {x.get('away','')}</b>\n"f"{live}"f"⏱ <b>{_period(x.get('scope'))}</b>\n"f"📊 <b>{_side(x.get('side'))}{line}{odd_txt}</b>\n"f"🏦 Подтверждений: <b>{int(x.get('books',0) or 0)}</b>\n"f"📉 Движение: <b>{float(x.get('median_delta_pct',0) or 0):.1f}%</b>\n"f"💪 Сила: <b>{float(x.get('strength',0) or 0):.0f}/100</b>")
def _send(x):
 token=unified_bot.BOT_TOKEN
 if not token:return 0
 try:png=render_proguz_card(x)
 except Exception as exc:
  log.exception("STRONG_PROGRUZ_CARD_RENDER_FAILED event=%s err=%s",x.get("event_id"),exc);png=None
 n=0
 for cid in get_subscribers():
  try:
   if png:
    r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":_caption(x),"parse_mode":"HTML"},files={"photo":("gool-strong-progruz.png",png,"image/png")},timeout=20)
   else:
    r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":str(cid),"text":_fmt(x),"parse_mode":"HTML","disable_web_page_preview":True},timeout=15)
   n+=int(r.ok)
  except requests.RequestException:pass
 return n

def poll_once():
 try:r=requests.get(URL,timeout=8);r.raise_for_status();rows=(r.json() or {}).get("strong") or []
 except Exception as e:log.warning("STRONG_PROGRUZ_OFFLINE %s",e);return 0
 sent=_load();now=time.time();n=0
 for x in rows:
  try:strength=float(x.get("strength",0) or 0)
  except Exception:continue
  if strength<MIN or int(x.get("books",0) or 0)<2:continue
  key=str(x.get("id") or "")
  if not key or now-float(sent.get(key,0) or 0)<COOLDOWN:continue
  delivered=_send(x)
  if delivered:sent[key]=now;n+=1;log.info("STRONG_PROGRUZ_CARD_SENT event=%s scope=%s side=%s score=%s minute=%s strength=%.1f books=%s",x.get("event_id"),x.get("scope"),x.get("side"),x.get("score_live"),x.get("minute"),strength,x.get("books"))
  if n>=3:break
 _save(sent);return n

def loop():
 log.info("REMOTE strong proguz relay active cards=on url=%s min=%.0f",URL,MIN)
 while True:
  poll_once();time.sleep(POLL)
threading.Thread(target=loop,name="strong-proguz-relay",daemon=True).start()
