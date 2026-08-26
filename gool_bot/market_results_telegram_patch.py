"""Owner-only Telegram report for settled market-movement recommendations."""
from __future__ import annotations
import telegram_subscribers as tg
import owner_market_tape_patch as omt
import market_recommendation_results as mrr

_BUTTON="📋 Итоги рынка"
_orig_handle=tg._handle_message

def _owner_keyboard():
 return {"keyboard":[
  [{"text":"🟢 В игре"},{"text":"📊 Отчёт"}],
  [{"text":"📈 Линия LIVE"},{"text":_BUTTON}],
  [{"text":"🧠 Анализ"}],
 ],"resize_keyboard":True}

# owner_market_tape_patch resolves this global function dynamically.
omt._owner_keyboard=_owner_keyboard

def _send(chat_id):
 if str(chat_id)!=str(tg._owner_chat_id()):
  tg._send_reply(chat_id,"⛔ Итоги рынка доступны только владельцу.");return
 tg._post_message(chat_id,mrr.build_results_text(),_owner_keyboard())

def _handle(message):
 chat=message.get("chat") or {};chat_id=chat.get("id");text=str(message.get("text") or "").strip();cmd=text.split(maxsplit=1)[0].lower() if text else ""
 if "@" in cmd:cmd=cmd.split("@",1)[0]
 if cmd=="/marketresults" or text.casefold()==_BUTTON.casefold():_send(chat_id);return
 _orig_handle(message)

tg._handle_message=_handle
tg.send_market_results=_send
