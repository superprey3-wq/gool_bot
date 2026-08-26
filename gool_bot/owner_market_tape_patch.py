"""Owner-only compact human-readable LIVE market movement report."""
from __future__ import annotations
import html, logging, re
import telegram_subscribers as tg
import market_node_bridge as bridge

logger=logging.getLogger("owner_market_tape_patch")
_BUTTON="📈 Линия LIVE";_orig_keyboard=tg._main_keyboard;_orig_handle_message=tg._handle_message;_orig_send_reply=tg._send_reply

def _owner(chat_id):return str(chat_id)==str(tg._owner_chat_id())
def _main_keyboard():return _orig_keyboard()
def _owner_keyboard():return {"keyboard":[[{"text":"🟢 В игре"},{"text":"📊 Отчёт"}],[{"text":_BUTTON},{"text":"🧠 Анализ"}]],"resize_keyboard":True}
def _send_reply(chat_id,text,keyboard=True):
 if keyboard and _owner(chat_id):
  if tg._post_message(chat_id,text,_owner_keyboard()):return True
  return tg._post_message(chat_id,text)
 return _orig_send_reply(chat_id,text,keyboard)
def _safe(v,default="—"):return html.escape(str(v)) if v not in (None,"") else default

def _line_from_raw(s):
 m=re.search(r"(?:^|\s)([-+]?\d+(?:\.\d+)?)\s*$",str(s or ""));return m.group(1) if m else ""
def _market_name(raw,type_id=None,line=None,group_id=None):
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
def _meaning(delta,name):
 if abs(delta)<.01:return "без заметного движения"
 if "ТБ" in name:return "рынок сильнее ждёт голы" if delta>0 else "рынок уходит от голов"
 if "ТМ" in name:return "рынок сильнее ждёт низ" if delta>0 else "рынок уходит от низа"
 return "вероятность исхода растёт" if delta>0 else "вероятность исхода падает"
def _gool_alignment(delta,name):
 if abs(delta)<1.5:return "⚪ к GOOL: нейтрально"
 if "ТБ" in name:return "🟢 к GOOL: ЗА сигнал" if delta>0 else "🔴 к GOOL: ПРОТИВ сигнала"
 if "ТМ" in name:return "🔴 к GOOL: ПРОТИВ сигнала" if delta>0 else "🟢 к GOOL: ЗА сигнал"
 return "⚪ к GOOL: рынок не голевой"
def _market_info(m):
 try:delta=float(m.get("delta_pp",0) or 0)
 except Exception:delta=0.0
 dot=str(m.get("dot") or ("🟣" if abs(delta)>=4 else "🟢" if delta>0 else "🔴" if delta<0 else "🟡"));name=_market_name(m.get("market"),m.get("type_id"),m.get("last_line"),m.get("group_id"));old=m.get("start_odds");new=m.get("last_odds")
 try:odds=f"{float(old):.2f} → {float(new):.2f}" if old is not None and new is not None else ""
 except Exception:odds=""
 strength="ОЧЕНЬ СИЛЬНО" if dot=="🟣" or abs(delta)>=4 else "заметно" if abs(delta)>=1.5 else "слабо";return delta,dot,name,odds,strength
def _market_row(m):
 delta,dot,name,odds,strength=_market_info(m);first=f"{dot} <b>{_safe(name)}</b>"+(f" · кэф <b>{odds}</b>" if odds else "");return first+f"\n   ↳ Δ {delta:+.2f} п.п. · {strength} · {_safe(_meaning(delta,name))}\n   ↳ {_gool_alignment(delta,name)}"
def _opposite_type(ti):
 try:ti=int(ti)
 except Exception:return None
 return {9:10,10:9,11:12,12:11,13:14,14:13,7:8,8:7,1:3,3:1}.get(ti)
def _same_line(a,b):
 try:return abs(float(a)-float(b))<1e-6
 except Exception:return a==b
def _recommendation(markets):
 candidates=[]
 for m in markets:
  delta,dot,name,odds,strength=_market_info(m)
  if abs(delta)<1.5 or "?" in name:continue
  chosen=m
  if delta<0:
   oti=_opposite_type(m.get("type_id"));ops=[]
   for x in markets:
    try:xti=int(x.get("type_id"))
    except Exception:continue
    if xti!=oti:continue
    if xti in {7,8,9,10,11,12,13,14} and not _same_line(x.get("last_line"),m.get("last_line")):continue
    try:xd=float(x.get("delta_pp",0) or 0)
    except Exception:continue
    if xd>0:ops.append((abs(xd),x))
   if not ops:continue
   chosen=max(ops,key=lambda z:z[0])[1]
  cd,_,cname,_,_=_market_info(chosen);candidates.append((abs(cd),chosen,cname))
 if not candidates:return "🎯 <b>Рекомендованная ставка:</b> сильное движение есть, но подтверждённой стороны для ставки нет"
 _,m,name=max(candidates,key=lambda x:x[0]);suffix=f" · текущий кэф {float(m.get('last_odds')):.2f}" if m.get("last_odds") is not None else "";return f"🎯 <b>Рекомендованная ставка по движению:</b> <b>{_safe(name)}</b>{suffix}"
def _tournament_line(row,diag):
 league=str(row.get("league") or row.get("tournament") or diag.get("league") or "").strip();country=str(row.get("country") or diag.get("country") or "").strip()
 if not league:return ""
 label=f"{country} · {league}" if country and country.casefold() not in league.casefold() else league;return f"🏆 {_safe(label)}"
def _market_line(row):
 home=str(row.get("home") or "?");away=str(row.get("away") or "?");entry=row.get("minute");score=row.get("score_at_signal") or "—"
 try:diag=bridge.diagnostic_for_match(home,away)
 except Exception:logger.exception("OWNER_MARKET_TAPE diag failed for %s - %s",home,away);diag={}
 tournament=_tournament_line(row,diag)
 if str(diag.get("match_mode") or "none")=="none":
  lines=[f"⚪ <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}' · {score}"]
  if tournament:lines.append(tournament)
  lines.extend(["↳ рынок пока не сопоставлен","🎯 <b>Рекомендованная ставка:</b> данных пока недостаточно"]);return "\n".join(lines)
 markets=list(diag.get("top_markets") or []);chosen=markets[:5]
 if not chosen:chosen=[{"market":diag.get("remote_market"),"delta_pp":diag.get("remote_delta",0),"dot":diag.get("final_dot"),"start_odds":diag.get("remote_start_odds"),"last_odds":diag.get("remote_last_odds")}]
 lines=[f"⚽ <b>{_safe(home)} — {_safe(away)}</b> · сигнал {entry}' · счёт {score}"]
 if tournament:lines.append(tournament)
 for m in chosen[:3]:lines.append(_market_row(m))
 lines.append(_recommendation(chosen));return "\n".join(lines)
def _send_market_tape(chat_id):
 if not _owner(chat_id):tg._send_reply(chat_id,"⛔ Линия LIVE доступна только владельцу.");return
 rows=tg._active_signal_rows()
 if not rows:tg._post_message(chat_id,"📈 <b>ЛИНИЯ LIVE</b>\n\nСейчас активных GOOL-сигналов нет.",_owner_keyboard());return
 lines=[f"📈 <b>ЛИНИЯ LIVE · {len(rows)}</b>","<i>До 3 самых сильных движений рынка по матчам, где GOOL уже дал сигнал.</i>",""]
 for row in rows[:6]:lines.extend([_market_line(row),""])
 if len(rows)>6:lines.append(f"…ещё {len(rows)-6} активных матчей")
 lines.append("<i>Рекомендация даётся только в сторону растущей рыночной вероятности. Если противоположная сторона не получена, бот не выдумывает ставку.</i>");tg._post_message(chat_id,"\n".join(lines),_owner_keyboard());logger.info("OWNER_MARKET_TAPE sent rows=%d",len(rows))
def _handle_message(message):
 chat=message.get("chat") or {};chat_id=chat.get("id");text=str(message.get("text") or "").strip();command=text.split(maxsplit=1)[0].lower() if text else ""
 if "@" in command:command=command.split("@",1)[0]
 if command=="/market" or text.casefold()==_BUTTON.casefold():_send_market_tape(chat_id);return
 _orig_handle_message(message)
 if chat_id is not None and _owner(chat_id) and command in {"/start","/menu"}:tg._post_message(chat_id,"👑 <i>Панель владельца</i>",_owner_keyboard())
tg._main_keyboard=_main_keyboard;tg._send_reply=_send_reply;tg._handle_message=_handle_message;tg.send_owner_market_tape=_send_market_tape
logger.info("Owner market tape: recommendation follows observed market direction only")
