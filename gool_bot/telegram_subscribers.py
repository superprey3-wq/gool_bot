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

def _main_keyboard():return {"keyboard":[[{"text":"🟢 В игре"},{"text":"📊 Отчёт"}],[{"text":"🧠 Анализ"}]],"resize_keyboard":True}
def _post_message(chat_id,text,reply_markup=None):
    token=_token()
    if not token:return False
    payload={"chat_id":str(chat_id),"text":text,"parse_mode":"HTML","disable_web_page_preview":True}
    if reply_markup is not None:payload["reply_markup"]=reply_markup
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json=payload,timeout=15)
        if r.ok:return True
        logger.warning("Telegram command reply failed: HTTP %s %s",r.status_code,r.text[:300])
    except requests.RequestException as exc:logger.warning("Telegram command reply failed: %s",exc)
    return False
def _send_reply(chat_id,text,keyboard=True):
    if keyboard:
        if _post_message(chat_id,text,_main_keyboard()):return True
        logger.warning("Telegram keyboard rejected for %s; retrying plain message",chat_id)
    return _post_message(chat_id,text)

def _active_signal_buttons():
    try:
        from report_now import _today_rows,_live_signal_rows,_current_live_ids
        live_ids=_current_live_ids()
        if live_ids is None:return None
        latest={}
        for r in _live_signal_rows(_today_rows()):
            eid=str(r.get("event_id","") or "")
            if not eid or eid not in live_ids:continue
            if eid not in latest or int(r.get("created_ts",0) or 0)>int(latest[eid].get("created_ts",0) or 0):latest[eid]=r
        rows=sorted(latest.values(),key=lambda r:int(r.get("created_ts",0) or 0),reverse=True)[:18]
        if not rows:return None
        buttons=[]
        for r in rows:
            label=f"⚽ {r.get('home')} — {r.get('away')}"
            if len(label)>46:label=label[:43]+"…"
            buttons.append([{"text":label,"callback_data":f"show:{r.get('event_id')}"}])
        return {"inline_keyboard":buttons}
    except Exception as exc:logger.exception("Could not build active signal buttons: %s",exc);return None

def _send_live(chat_id):
    _send_reply(chat_id,"🔎 Проверяю активные сигналы…")
    try:
        from report_now import build_live_signals_text
        markup=_active_signal_buttons();_post_message(chat_id,build_live_signals_text(),markup);logger.info("Telegram in-game list sent to: %s",chat_id)
    except Exception as exc:logger.exception("Telegram in-game failed: %s",exc);_send_reply(chat_id,"⚠️ Не удалось получить активные сигналы прямо сейчас.")
def _send_report(chat_id):
    _send_reply(chat_id,"📊 Собираю текущий отчёт…")
    try:
        from report_now import build_report_text
        # Active matches appear as tappable buttons directly under the report.
        _post_message(chat_id,build_report_text(),_active_signal_buttons());logger.info("Telegram report sent to: %s",chat_id)
    except Exception as exc:logger.exception("Telegram /report failed: %s",exc);_send_reply(chat_id,"⚠️ Не удалось собрать отчёт прямо сейчас. Ошибка записана в лог.")
def _handle_message(message:dict):
    chat=message.get("chat") or {};chat_id=chat.get("id")
    if chat_id is None:return
    text=str(message.get("text") or "").strip();command=text.split(maxsplit=1)[0].lower()
    if "@" in command:command=command.split("@",1)[0]
    if command in {"/start","/menu"}:
        subscribe(chat_id);name=str((message.get("from") or {}).get("first_name") or "").strip();greeting=f", {name}" if name else ""
        _send_reply(chat_id,"✅ <b>GOOL AI подключён</b>"+greeting+"!\n\nLIVE-сигналы будут приходить сюда. Кнопка <b>🟢 В игре</b> показывает только активные входы. В отчёте активный матч можно нажать и сразу снова открыть его карточку.\n\n/stop — отключить рассылку\n/status — подписка\n/report — отчёт\n/analysis — анализ")
        logger.info("Telegram subscriber activated/menu opened: %s",chat_id)
    elif command=="/stop":
        if str(chat_id)==_owner_chat_id():_send_reply(chat_id,"👑 Основной чат владельца всегда остаётся активным.");return
        unsubscribe(chat_id);_send_reply(chat_id,"🔕 Рассылка GOOL AI отключена. Вернуть её можно командой /start.");logger.info("Telegram subscriber deactivated: %s",chat_id)
    elif command=="/status":_send_reply(chat_id,"✅ Подписка активна." if str(chat_id) in set(get_subscribers()) else "🔕 Подписка отключена. Отправь /start.")
    elif command=="/live" or text.casefold() in {"🟢 в игре","в игре"}:_send_live(chat_id)
    elif command=="/report" or text.casefold()=="📊 отчёт":_send_report(chat_id)
    elif command=="/analysis" or text.casefold()=="🧠 анализ":
        _send_reply(chat_id,"🧠 Анализирую сегодняшние закрытые входы…")
        try:
            from signal_analysis import build_analysis_text
            _send_reply(chat_id,build_analysis_text());logger.info("Telegram analysis sent to: %s",chat_id)
        except Exception as exc:logger.exception("Telegram /analysis failed: %s",exc);_send_reply(chat_id,"⚠️ Не удалось выполнить анализ. Ошибка записана в лог.")

def _answer_callback(callback_id,text=None):
    token=_token()
    if not token:return
    try:requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery",json={"callback_query_id":str(callback_id),"text":text or ""},timeout=10)
    except requests.RequestException:pass

def _handle_callback(query:dict):
    cid=query.get("id");data=str(query.get("data") or "");msg=query.get("message") or {};chat=(msg.get("chat") or {});chat_id=chat.get("id")
    if not cid or chat_id is None:return
    if not data.startswith("show:"):return
    event_id=data.split(":",1)[1]
    from signal_card_archive import get_entry_card
    card=get_entry_card(event_id)
    if not card:
        _answer_callback(cid,"Карточка была отправлена до обновления бота")
        _send_reply(chat_id,"ℹ️ Эту старую карточку бот ещё не успел сохранить. Новые сигналы уже будут открываться по нажатию.")
        return
    token=_token();payload={"chat_id":str(chat_id),"photo":card.get("file_id"),"caption":card.get("caption") or "🔥 GOOL AI • МОЖНО ЗАХОДИТЬ"}
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",json=payload,timeout=20)
        if r.ok:_answer_callback(cid,"Открываю сигнал")
        else:_answer_callback(cid,"Не удалось открыть карточку");logger.warning("Archived card send failed: %s",r.text[:200])
    except requests.RequestException as exc:_answer_callback(cid,"Ошибка Telegram");logger.warning("Archived card send failed: %s",exc)

def _poll_once(offset):
    token=_token()
    if not token:return offset
    params={"timeout":25,"allowed_updates":json.dumps(["message","callback_query"])}
    if offset is not None:params["offset"]=offset
    try:
        r=requests.get(f"https://api.telegram.org/bot{token}/getUpdates",params=params,timeout=35)
        if not r.ok:logger.warning("Telegram getUpdates failed: HTTP %s %s",r.status_code,r.text[:200]);return offset
        for update in (r.json().get("result") or []):
            uid=update.get("update_id")
            if isinstance(uid,int):offset=uid+1
            try:
                msg=update.get("message");cb=update.get("callback_query")
                if isinstance(msg,dict):_handle_message(msg)
                elif isinstance(cb,dict):_handle_callback(cb)
            except Exception as exc:logger.exception("Telegram update handler failed but polling continues: %s",exc)
    except (requests.RequestException,ValueError) as exc:logger.warning("Telegram polling failed: %s",exc)
    except Exception as exc:logger.exception("Unexpected Telegram polling error: %s",exc)
    return offset
async def polling_loop():
    offset=None;logger.info("Telegram command polling started")
    while True:
        try:offset=await asyncio.to_thread(_poll_once,offset)
        except Exception as exc:logger.exception("Telegram polling iteration crashed; restarting: %s",exc)
        await asyncio.sleep(.5)
