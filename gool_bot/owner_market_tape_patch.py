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

def _line_from_raw(s):
 m=re.search(r"(?:^|\s)([-+]?\d+(?:\.\d+)?)\s*$",str(s or ""))
 return m.group(1) if m else ""

def _market_name(raw):
 """Translate common BetB2B football ids into betting-language labels."""
 s=" ".join(str(raw or "").split());low=s.casefold();line=_line_from_raw(s)
 if not s:return "рынок не указан"
 # Human-readable names supplied by provider/node.
 aliases=(("team total home","ИТ хозяев"),("team total away","ИТ гостей"),("home team total","ИТ хозяев"),("away team total","ИТ гостей"),("first half total","Тотал 1-го тайма"),("second half total","Тотал 2-го тайма"),("match total","Тотал матча"),("total over","ТБ"),("total under","ТМ"),("handicap","Фора"),("home win","П1"),("away win","П2"))
 for key,label in aliases:
  if key in low:return f"{label}{(' '+line) if line else ''}"
 # BetB2B fallback ids used by this collector.
 g=re.search(r"\bG(\d+)\b",s,re.I);t=re.search(r"\bT(\d+)\b",s,re.I)
 gi=int(g.group(1)) if g else None;ti=int(t.group(1)) if t else None
 if gi==4 and ti==9:return f"⚽ Тотал матча · ТБ {line or '?'}"
 if gi==4 and ti==10:return f"⚽ Тотал матча · ТМ {line or '?'}"
 if ti==11:return f"⚽ ИТ команды 1 · ТМ {line or '?'}"
 if ti==12:return f"⚽ ИТ команды 1 · ТБ {line or '?'}"
 if ti==13:return f"⚽ ИТ команды 2 · ТМ {line or '?'}"
 if ti==14:return f"⚽ ИТ команды 2 · ТБ {line or '?'}"
 if gi==1 and ti==1:return "🏆 Победа хозяев · П1"
 if gi==1 and ti==3:return "🏆 Победа гостей · П2"
 if ti==7:return f"📐 Фора команды 1{(' '+line) if line else ''}"
 if ti==8:return f"📐 Фора команды 2{(' '+line) if line else ''}"
 return s[:55]+("…" if len(s)>55 else "")

def _interpret(delta,dot,market):
 if abs(delta)<.01:return "рынок почти без движения"
 growing=delta>0
 m=str(market)
 if "ТБ" in m or "ИТ" in m and "ТБ" in m:
  side="рынок усиливает сценарий голов" if growing else "рынок охлаждает сценарий голов"
 elif "ТМ" in m:
  side="рынок сильнее ждёт низ" if growing else "рынок уходит от низа"
 else:
  side="вероятность этого исхода растёт" if growing else "вероятность этого исхода падает"
 strength="ОЧЕНЬ СИЛЬНО" if dot=="🟣" or abs(delta)>=4 else "заметно" if abs(delta)>=1.5 else "слабо"
 return f"{strength} · {side}"

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
 arrow="⬇️ кэф" if delta>0 else "⬆️ кэф" if delta<0 else "➡️ кэф"
 return (f"{dot} <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}'\n"
         f"↳ <b>{_safe(market)}</b>\n"
         f"↳ {arrow} · Δ <b>{delta:+.2f} п.п.</b>\n"
         f"↳ {_safe(_interpret(delta,dot,market))}")

def _send_market_tape(chat_id):
 if not _owner(chat_id):tg._send_reply(chat_id,"⛔ Линия LIVE доступна только владельцу.");return
 rows=tg._active_signal_rows()
 if not rows:tg._post_message(chat_id,"📈 <b>ЛИНИЯ LIVE</b>\n\nСейчас активных GOOL-сигналов нет.",_owner_keyboard());return
 lines=[f"📈 <b>ЛИНИЯ LIVE · {len(rows)}</b>","<i>Самое сильное движение рынка по матчам, где GOOL уже дал сигнал.</i>",""]
 for row in rows[:8]:lines.extend([_market_line(row),""])
 if len(rows)>8:lines.append(f"…ещё {len(rows)-8} активных матчей")
 lines.append("<i>⬇️ кэф = рынок сильнее верит в выбранный исход. ⬆️ кэф = рынок от него уходит.</i>")
 tg._post_message(chat_id,"\n".join(lines),_owner_keyboard());logger.info("OWNER_MARKET_TAPE sent rows=%d",len(rows))

def _handle_message(message):
 chat=message.get("chat") or {};chat_id=chat.get("id");text=str(message.get("text") or "").strip();command=text.split(maxsplit=1)[0].lower() if text else ""
 if "@" in command:command=command.split("@",1)[0]
 if command=="/market" or text.casefold()==_BUTTON.casefold():_send_market_tape(chat_id);return
 _orig_handle_message(message)
 if chat_id is not None and _owner(chat_id) and command in {"/start","/menu"}:tg._post_message(chat_id,"👑 <i>Панель владельца</i>",_owner_keyboard())

tg._main_keyboard=_main_keyboard;tg._handle_message=_handle_message;tg.send_owner_market_tape=_send_market_tape
logger.info("Owner-only decoded market tape enabled")
