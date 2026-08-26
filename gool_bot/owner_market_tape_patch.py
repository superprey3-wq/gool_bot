"""Owner-only compact human-readable LIVE market movement report."""
from __future__ import annotations
import html, logging, re
import telegram_subscribers as tg
import market_node_bridge as bridge

logger=logging.getLogger("owner_market_tape_patch")
_BUTTON="📈 Линия LIVE";_orig_keyboard=tg._main_keyboard;_orig_handle_message=tg._handle_message;_orig_send_reply=tg._send_reply

def _owner(chat_id):return str(chat_id)==str(tg._owner_chat_id())
def _main_keyboard():return _orig_keyboard()
def _owner_keyboard():
 # Keep the normal public keyboard intact, but give the owner a stable 2x2 panel.
 return {"keyboard":[[{"text":"🟢 В игре"},{"text":"📊 Отчёт"}],[{"text":_BUTTON},{"text":"🧠 Анализ"}]],"resize_keyboard":True}
def _send_reply(chat_id,text,keyboard=True):
 # telegram_subscribers handlers resolve _send_reply dynamically, so this makes
 # every owner reply restore the private button instead of overwriting it with
 # the public three-button keyboard.
 if keyboard and _owner(chat_id):
  if tg._post_message(chat_id,text,_owner_keyboard()):return True
  return tg._post_message(chat_id,text)
 return _orig_send_reply(chat_id,text,keyboard)
def _safe(v,default="—"):return html.escape(str(v)) if v not in (None,"") else default

def _line_from_raw(s):
 m=re.search(r"(?:^|\s)([-+]?\d+(?:\.\d+)?)\s*$",str(s or ""));return m.group(1) if m else ""

def _market_name(raw, type_id=None, line=None, group_id=None):
 s=" ".join(str(raw or "").split());low=s.casefold();ln=str(line if line is not None else _line_from_raw(s) or "?")
 try:ti=int(type_id) if type_id is not None else None
 except Exception:ti=None
 try:gi=int(group_id) if group_id is not None else None
 except Exception:gi=None
 if ti is None:
  g=re.search(r"\bG(\d+)\b",s,re.I);t=re.search(r"\bT(\d+)\b",s,re.I);gi=int(g.group(1)) if g else gi;ti=int(t.group(1)) if t else ti
 aliases=(("team total home","ИТ хозяев"),("team total away","ИТ гостей"),("home team total","ИТ хозяев"),("away team total","ИТ гостей"),("first half total","Тотал 1-го тайма"),("second half total","Тотал 2-го тайма"),("match total","Тотал матча"),("total over","ТБ"),("total under","ТМ"),("handicap","Фора"),("home win","П1"),("away win","П2"))
 for key,label in aliases:
  if key in low:return f"{label}{(' '+ln) if ln!='?' and ('total' in key or 'handicap' in key) else ''}"
 if gi==4 and ti==9:return f"⚽ Тотал матча · ТБ {ln}"
 if gi==4 and ti==10:return f"⚽ Тотал матча · ТМ {ln}"
 if ti==11:return f"⚽ ИТ1 · ТМ {ln}"
 if ti==12:return f"⚽ ИТ1 · ТБ {ln}"
 if ti==13:return f"⚽ ИТ2 · ТМ {ln}"
 if ti==14:return f"⚽ ИТ2 · ТБ {ln}"
 if gi==1 and ti==1:return "🏆 П1"
 if gi==1 and ti==3:return "🏆 П2"
 if ti==7:return f"📐 Фора 1 · {ln}"
 if ti==8:return f"📐 Фора 2 · {ln}"
 return s[:55]+("…" if len(s)>55 else "") if s else "рынок"

def _is_goal_total(m):
 try:return int(m.get("type_id")) in {9,10,11,12,13,14}
 except Exception:return "total" in str(m.get("market") or "").casefold()

def _meaning(delta,name):
 if abs(delta)<.01:return "без заметного движения"
 is_over="ТБ" in name;is_under="ТМ" in name
 if is_over:return "рынок сильнее ждёт голы" if delta>0 else "рынок уходит от голов"
 if is_under:return "рынок сильнее ждёт низ" if delta>0 else "рынок уходит от низа"
 return "вероятность исхода растёт" if delta>0 else "вероятность исхода падает"

def _market_row(m):
 try:delta=float(m.get("delta_pp",0) or 0)
 except Exception:delta=0.0
 dot=str(m.get("dot") or ("🟣" if abs(delta)>=4 else "🟢" if delta>0 else "🔴" if delta<0 else "🟡"))
 name=_market_name(m.get("market"),m.get("type_id"),m.get("last_line"),m.get("group_id"))
 old=m.get("start_odds");new=m.get("last_odds")
 try:odds=f"{float(old):.2f} → {float(new):.2f}" if old is not None and new is not None else ""
 except Exception:odds=""
 strength="ОЧЕНЬ СИЛЬНО" if dot=="🟣" or abs(delta)>=4 else "заметно" if abs(delta)>=1.5 else "слабо"
 return f"{dot} <b>{_safe(name)}</b>" + (f" · кэф <b>{odds}</b>" if odds else "") + f"\n   ↳ Δ {delta:+.2f} п.п. · {strength} · {_safe(_meaning(delta,name))}"

def _tournament_line(row,diag):
 league=str(row.get("league") or row.get("tournament") or diag.get("league") or "").strip()
 country=str(row.get("country") or diag.get("country") or "").strip()
 if not league:return ""
 label=f"{country} · {league}" if country and country.casefold() not in league.casefold() else league
 return f"🏆 {_safe(label)}"

def _market_line(row):
 home=str(row.get("home") or "?");away=str(row.get("away") or "?");entry=row.get("minute");score=row.get("score_at_signal") or "—"
 try:diag=bridge.diagnostic_for_match(home,away)
 except Exception:logger.exception("OWNER_MARKET_TAPE diag failed for %s - %s",home,away);diag={}
 tournament=_tournament_line(row,diag)
 if str(diag.get("match_mode") or "none")=="none":
  lines=[f"⚪ <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}' · {score}"]
  if tournament:lines.append(tournament)
  lines.append("↳ рынок пока не сопоставлен")
  return "\n".join(lines)
 markets=list(diag.get("top_markets") or [])
 totals=[m for m in markets if _is_goal_total(m)]
 chosen=(totals or markets)[:3]
 if not chosen:
  chosen=[{"market":diag.get("remote_market"),"delta_pp":diag.get("remote_delta",0),"dot":diag.get("final_dot"),"start_odds":diag.get("remote_start_odds"),"last_odds":diag.get("remote_last_odds")}]
 lines=[f"⚽ <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}' · счёт {score}"]
 if tournament:lines.append(tournament)
 for m in chosen:lines.append(_market_row(m))
 return "\n".join(lines)

def _send_market_tape(chat_id):
 if not _owner(chat_id):tg._send_reply(chat_id,"⛔ Линия LIVE доступна только владельцу.");return
 rows=tg._active_signal_rows()
 if not rows:tg._post_message(chat_id,"📈 <b>ЛИНИЯ LIVE</b>\n\nСейчас активных GOOL-сигналов нет.",_owner_keyboard());return
 lines=[f"📈 <b>ЛИНИЯ LIVE · {len(rows)}</b>","<i>До 3 самых сильных движений тоталов по матчам, где GOOL уже дал сигнал.</i>",""]
 for row in rows[:6]:lines.extend([_market_line(row),""])
 if len(rows)>6:lines.append(f"…ещё {len(rows)-6} активных матчей")
 lines.append("<i>Кэф ↓ на ТБ = рынок сильнее ждёт голы. Кэф ↓ на ТМ = рынок сильнее ждёт низ.</i>")
 tg._post_message(chat_id,"\n".join(lines),_owner_keyboard());logger.info("OWNER_MARKET_TAPE sent rows=%d",len(rows))

def _handle_message(message):
 chat=message.get("chat") or {};chat_id=chat.get("id");text=str(message.get("text") or "").strip();command=text.split(maxsplit=1)[0].lower() if text else ""
 if "@" in command:command=command.split("@",1)[0]
 if command=="/market" or text.casefold()==_BUTTON.casefold():_send_market_tape(chat_id);return
 _orig_handle_message(message)
 if chat_id is not None and _owner(chat_id) and command in {"/start","/menu"}:tg._post_message(chat_id,"👑 <i>Панель владельца</i>",_owner_keyboard())

tg._main_keyboard=_main_keyboard;tg._send_reply=_send_reply;tg._handle_message=_handle_message;tg.send_owner_market_tape=_send_market_tape
logger.info("Owner-only multi-line market tape with persistent 2x2 owner keyboard enabled")
