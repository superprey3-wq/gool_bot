"""Telegram subscriber registry and command polling."""
from __future__ import annotations
import asyncio,json,logging,os
from pathlib import Path
from typing import Iterable
import requests
logger=logging.getLogger("telegram_subscribers")
SUBSCRIBERS_FILE=Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE",str(Path(__file__).with_name("telegram_subscribers.json"))))
def _token():
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
    if token and ":" not in token:
        bot_id=os.getenv("TELEGRAM_BOT_ID","").strip()
        if bot_id.isdigit():token=f"{bot_id}:{token}"
    return token
def _owner_chat_id():return os.getenv("TELEGRAM_CHAT_ID","").strip()
def _read_saved():
    if not SUBSCRIBERS_FILE.exists():return set()
    try:
        data=json.loads(SUBSCRIBERS_FILE.read_text(encoding="utf-8"));return {str(x).strip() for x in data if str(x).strip()} if isinstance(data,list) else set()
    except Exception as exc:logger.warning("Could not read Telegram subscribers: %s",exc);return set()
def _write_saved(chat_ids:Iterable[str]):
    values=sorted({str(x).strip() for x in chat_ids if str(x).strip()})
    try:SUBSCRIBERS_FILE.parent.mkdir(parents=True,exist_ok=True);SUBSCRIBERS_FILE.write_text(json.dumps(values,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception as exc:logger.error("Could not save Telegram subscribers: %s",exc)
def get_subscribers():
    s=_read_saved();owner=_owner_chat_id()
    if owner:s.add(owner)
    return sorted(s)
def subscribe(chat_id):
    chat_id=str(chat_id).strip()
    if not chat_id:return False
    s=_read_saved();before=len(s);s.add(chat_id);_write_saved(s);return len(s)!=before
def unsubscribe(chat_id):
    chat_id=str(chat_id).strip();s=_read_saved();existed=chat_id in s;s.discard(chat_id);_write_saved(s);return existed
def _send_reply(chat_id,text):
    token=_token()
    if not token:return
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":str(chat_id),"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=15)
        if not r.ok:logger.warning("Telegram command reply failed: HTTP %s %s",r.status_code,r.text[:200])
    except requests.RequestException as exc:logger.warning("Telegram command reply failed: %s",exc)
def _handle_message(message:dict):
    chat=message.get("chat") or {};chat_id=chat.get("id")
    if chat_id is None:return
    text=str(message.get("text") or "").strip();command=text.split(maxsplit=1)[0].lower()
    if "@" in command:command=command.split("@",1)[0]
    if command=="/start":
        subscribe(chat_id);name=str((message.get("from") or {}).get("first_name") or "").strip();greeting=f", {name}" if name else ""
        _send_reply(chat_id,"✅ <b>GOOL AI подключён</b>"+greeting+"!\n\nТеперь сюда будут приходить LIVE-сигналы бота.\nЧтобы отключить рассылку: /stop\nПроверить подписку: /status\nТекущий итог: /report\nАнализ качества сигналов: /analysis")
        logger.info("Telegram subscriber activated: %s",chat_id)
    elif command=="/stop":
        if str(chat_id)==_owner_chat_id():_send_reply(chat_id,"👑 Основной чат владельца всегда остаётся активным.");return
        unsubscribe(chat_id);_send_reply(chat_id,"🔕 Рассылка GOOL AI отключена. Вернуть её можно командой /start.");logger.info("Telegram subscriber deactivated: %s",chat_id)
    elif command=="/status":_send_reply(chat_id,"✅ Подписка активна." if str(chat_id) in set(get_subscribers()) else "🔕 Подписка отключена. Отправь /start.")
    elif command=="/report":
        _send_reply(chat_id,"📊 Собираю текущий отчёт…")
        try:
            from report_now import build_report_text
            _send_reply(chat_id,build_report_text());logger.info("Telegram report sent to: %s",chat_id)
        except Exception as exc:logger.exception("Telegram /report failed: %s",exc);_send_reply(chat_id,"⚠️ Не удалось собрать отчёт прямо сейчас. Ошибка записана в лог.")
    elif command=="/analysis":
        _send_reply(chat_id,"🧠 Анализирую сегодняшние закрытые входы…")
        try:
            from signal_analysis import build_analysis_text
            _send_reply(chat_id,build_analysis_text());logger.info("Telegram analysis sent to: %s",chat_id)
        except Exception as exc:logger.exception("Telegram /analysis failed: %s",exc);_send_reply(chat_id,"⚠️ Не удалось выполнить анализ. Ошибка записана в лог.")
def _poll_once(offset):
    token=_token()
    if not token:return offset
    params={"timeout":25,"allowed_updates":json.dumps(["message"])}
    if offset is not None:params["offset"]=offset
    try:
        r=requests.get(f"https://api.telegram.org/bot{token}/getUpdates",params=params,timeout=35)
        if not r.ok:logger.warning("Telegram getUpdates failed: HTTP %s",r.status_code);return offset
        for update in (r.json().get("result") or []):
            uid=update.get("update_id")
            if isinstance(uid,int):offset=uid+1
            msg=update.get("message")
            if isinstance(msg,dict):_handle_message(msg)
    except (requests.RequestException,ValueError) as exc:logger.warning("Telegram polling failed: %s",exc)
    return offset
async def polling_loop():
    offset=None;logger.info("Telegram command polling started")
    while True:offset=await asyncio.to_thread(_poll_once,offset);await asyncio.sleep(.5)
