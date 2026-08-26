"""Owner-only compact human-readable LIVE market movement report."""
from __future__ import annotations
import html, logging, re
import telegram_subscribers as tg
import market_node_bridge as bridge

logger=logging.getLogger("owner_market_tape_patch")
_BUTTON="📈 Линия LIVE";_orig_keyboard=tg._main_keyboard;_orig_handle_message=tg._handle_message

def _owner(chat_id):return str(chat_id)==str(tg._owner_chat_id())
def _main_keyboard():return _orig_keyboard()
def _owner_keyboard():
 kb=_orig_keyboard();rows=list(kb.get("keyboard") or [])
 if not any(any(str(b.get("text"))==_BUTTON for b in r if isinstance(b,dict)) for r in rows):rows.append([{"text":_BUTTON}])
 return {"keyboard":rows,"resize_keyboard":True}
def _safe(v,default="—"):return html.escape(str(v)) if v not in (None,"") else default

def _market_name(raw):
 """Translate known labels; never pretend unknown G/T ids are decoded."""
 s=" ".join(str(raw or "").split());low=s.casefold()
 if not s:return "рынок не указан"
 # Human labels if the secondary node already supplies semantic names.
 repl=(("team total home","ИТБ хозяев"),("team total away","ИТБ гостей"),("home team total","ИТ хозяев"),("away team total","ИТ гостей"),("first half total","тотал 1-го тайма"),("second half total","тотал 2-го тайма"),("match total","тотал матча"),("total over","ТБ"),("total under","ТМ"),("handicap","фора"),("home win","П1"),("away win","П2"))
 for key,label in repl:
  if key in low:return label + (" " + s.split(key,1)[-1].strip() if low.startswith(key) else "")
 # Raw provider ids are deliberately marked as such until node sends dictionary.
 if re.search(r"\bG\d+\s*/\s*T\d+",s,re.I):return "рынок букмекера (код %s)"%s
 return s[:55]+("…" if len(s)>55 else "")

def _interpret(delta,dot):
 if abs(delta)<.01:return "рынок стоит на месте"
 direction="коэффициент падает / вероятность растёт" if delta>0 else "коэффициент растёт / вероятность падает"
 strength="очень сильное" if dot=="🟣" or abs(delta)>=4 else "заметное" if abs(delta)>=1.5 else "слабое"
 return f"{strength} движение · {direction}"

def _market_line(row):
 home=str(row.get("home") or "?");away=str(row.get("away") or "?");entry=row.get("minute")
 try:diag=bridge.diagnostic_for_match(home,away)
 except Exception:logger.exception("OWNER_MARKET_TAPE diag failed for %s - %s",home,away);diag={}
 mode=str(diag.get("match_mode") or "none")
 if mode=="none":return f"⚪ <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}'\n↳ рынок пока не сопоставлен"
 dot=str(diag.get("final_dot") or "⚪")
 try:delta=float(diag.get("remote_delta",0) or 0)
 except Exception:delta=0.0
 market=_market_name(diag.get("remote_market") or "")
 return (f"{dot} <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}'\n"
         f"↳ {_safe(market)}\n"
         f"↳ <b>{delta:+.2f} п.п.</b> · {_safe(_interpret(delta,dot))}")

def _send_market_tape(chat_id):
 if not _owner(chat_id):tg._send_reply(chat_id,"⛔ Линия LIVE доступна только владельцу.");return
 rows=tg._active_signal_rows()
 if not rows:tg._post_message(chat_id,"📈 <b>ЛИНИЯ LIVE</b>\n\nСейчас активных GOOL-сигналов нет.",_owner_keyboard());return
 lines=[f"📈 <b>ЛИНИЯ LIVE · {len(rows)}</b>","<i>Что рынок делает сейчас по матчам, где GOOL уже дал сигнал.</i>",""]
 for row in rows[:8]:lines.extend([_market_line(row),""])
 if len(rows)>8:lines.append(f"…ещё {len(rows)-8} активных матчей")
 lines.append("<i>+Δ = вероятность выбранного исхода выросла; −Δ = снизилась. Сырые G/T-коды помечаются как коды букмекера, пока не получим их словарь.</i>")
 tg._post_message(chat_id,"\n".join(lines),_owner_keyboard());logger.info("OWNER_MARKET_TAPE sent rows=%d",len(rows))

def _handle_message(message):
 chat=message.get("chat") or {};chat_id=chat.get("id");text=str(message.get("text") or "").strip();command=text.split(maxsplit=1)[0].lower() if text else ""
 if "@" in command:command=command.split("@",1)[0]
 if command=="/market" or text.casefold()==_BUTTON.casefold():_send_market_tape(chat_id);return
 _orig_handle_message(message)
 if chat_id is not None and _owner(chat_id) and command in {"/start","/menu"}:tg._post_message(chat_id,"👑 <i>Панель владельца</i>",_owner_keyboard())

tg._main_keyboard=_main_keyboard;tg._handle_message=_handle_message;tg.send_owner_market_tape=_send_market_tape
logger.info("Owner-only human-readable market tape enabled")
