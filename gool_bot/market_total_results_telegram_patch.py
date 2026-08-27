"""Owner-only Telegram report for automatic sharp-total alerts."""
from __future__ import annotations
import logging
import telegram_subscribers as tg
import owner_market_tape_patch as owner_ui
import market_test_signal

log=logging.getLogger("market_total_results_telegram_patch")
BUTTON="🚨 Итоги прогрузов"
_orig_handle=tg._handle_message

def _owner(chat_id):return str(chat_id)==str(tg._owner_chat_id())
def _keyboard():
 return {"keyboard":[[{"text":"🟢 В игре"},{"text":"📊 Отчёт"}],[{"text":"📈 Линия LIVE"},{"text":"🧠 Анализ"}],[{"text":BUTTON},{"text":"📋 Итоги рынка"}]],"resize_keyboard":True}

def _handle(message):
 chat=message.get("chat") or {};chat_id=chat.get("id");text=str(message.get("text") or "").strip();cmd=text.split(maxsplit=1)[0].lower() if text else ""
 if "@" in cmd:cmd=cmd.split("@",1)[0]
 if cmd=="/progruzresults" or text.casefold()==BUTTON.casefold():
  if not _owner(chat_id):tg._send_reply(chat_id,"⛔ Отчёт прогрузов доступен только владельцу.");return
  tg._post_message(chat_id,market_test_signal.build_results_text(),_keyboard());return
 _orig_handle(message)

# owner_market_tape_patch resolves _owner_keyboard dynamically, so replacing it
# keeps the extra button visible after /menu and after every owner market report.
owner_ui._owner_keyboard=_keyboard
tg._handle_message=_handle
log.info("Owner sharp-total results button enabled")
