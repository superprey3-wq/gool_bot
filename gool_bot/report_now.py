"""On-demand GOOL 2.0 report: CORE + 1H goal + 2H O1.5."""
from __future__ import annotations
import asyncio,time
from datetime import datetime
from zoneinfo import ZoneInfo
from live_engine import discover_live_matches,fetch_summary
from daily_report import _score_from_summary
from signal_journal import all_signals
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15
MOSCOW=ZoneInfo("Europe/Moscow")
WIN={"+","win","won"};LOSS={"-","loss","lost"};PENDING={"","pending","wait","waiting"}

def _today_rows():
 today=datetime.now(MOSCOW).date().isoformat();out=[]
 for r in all_signals():
  try:d=datetime.fromtimestamp(int(r.get("created_ts",0)),MOSCOW).date().isoformat()
  except:continue
  if d==today and r.get("kind")=="live":out.append(r)
 return out

def _core_rows(rows):return [r for r in rows if str(r.get("engine") or "core") not in {FIRST_HALF_GOAL,SECOND_HALF_OVER15} and str(r.get("reason") or "signal") in {"signal","reentry"}]
def _engine_rows(rows,e):return [r for r in rows if str(r.get("engine") or "")==e]
def _is_pending_entry(r):return str(r.get("result") or "pending").strip().lower() in PENDING

def _current_live_ids():
 try:return {str(m.event_id) for m in asyncio.run(discover_live_matches())}
 except Exception:return None

def _parse_score(v):
 try:a,b=str(v or "0:0").split(":",1);return int(a),int(b)
 except:return 0,0

def _market_label(p):
 if not isinstance(p,dict):return "аналитический сигнал"
 k=str(p.get("market_type") or p.get("market") or "TOTAL").upper();line=p.get("line")
 if k=="BTTS":return "ОЗ — Да"
 if k=="TEAM_TOTAL_HOME":return f"ИТБ хозяев {line:g}" if isinstance(line,(int,float)) else "ИТБ хозяев"
 if k=="TEAM_TOTAL_AWAY":return f"ИТБ гостей {line:g}" if isinstance(line,(int,float)) else "ИТБ гостей"
 if line is not None:
  try:return f"ТБ {float(line):g}"
  except:pass
 return k

def _market_hit(primary,final_score):
 if not isinstance(primary,dict):return None
 h,a=_parse_score(final_score);k=str(primary.get("market_type") or primary.get("market") or "TOTAL").upper()
 if k=="BTTS":return h>0 and a>0
 try:line=float(primary.get("line"))
 except:return None
 if k=="TEAM_TOTAL_HOME":return h>line
 if k=="TEAM_TOTAL_AWAY":return a>line
 if k in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER"}:return h+a>line
 return None

def _core_status(r,live_ids,cache):
 stored=str(r.get("result") or "pending").lower();eid=str(r.get("event_id") or "")
 if stored in WIN:return "win",str(r.get("final_score") or "✓")
 if stored in LOSS:return "loss",str(r.get("final_score") or "—")
 if live_ids is not None and eid in live_ids:return "pending",str(r.get("score_at_signal") or "")
 if eid not in cache:
  try:cache[eid]=fetch_summary(eid)
  except:cache[eid]=None
 body=cache.get(eid)
 if not body:return "pending",str(r.get("score_at_signal") or "")
 try:fh,fa,_,_=_score_from_summary(body);score=f"{fh}:{fa}"
 except:return "pending",str(r.get("score_at_signal") or "")
 hit=_market_hit(r.get("primary"),score)
 return ("win" if hit else "loss" if hit is False else "pending"),score

def build_live_signals_text()->str:
 rows=[r for r in _today_rows() if _is_pending_entry(r)];ids=_current_live_ids()
 if ids is not None:rows=[r for r in rows if str(r.get("event_id") or "") in ids]
 if not rows:return "🟢 <b>В ИГРЕ</b>\n\nСейчас незакрытых сигналов нет."
 lines=[f"🟢 <b>В ИГРЕ — {len(rows)}</b>","<i>CORE + две стратегии GOOL 2.0.</i>",""]
 for r in rows[-20:]:
  e=str(r.get("engine") or "core");tag="CORE" if e=="core" else "ГОЛ 1Т" if e==FIRST_HALF_GOAL else "ТБ1.5 2Т"
  lines.append(f"⏳ <b>{tag}</b> · {r.get('home')} — {r.get('away')} | {r.get('minute')}' {r.get('score_at_signal')}")
 return "\n".join(lines)

def _section(title,rows):
 w=sum(str(r.get("result") or "").lower() in WIN for r in rows);l=sum(str(r.get("result") or "").lower() in LOSS for r in rows);p=len(rows)-w-l;s=w+l
 odds=[float(r.get("odd")) for r in rows if str(r.get("odd") or "").replace('.','',1).isdigit() and float(r.get("odd"))>1]
 out=["",title,f"Сигналов: <b>{len(rows)}</b> · ✅ {w} · ❌ {l} · ⏳ {p}"]
 if s:out.append(f"🎯 Проходимость: <b>{round(w/s*100)}%</b>")
 if odds:out.append(f"💰 Свежих LIVE-кэфов: <b>{len(odds)}</b> · средний <b>{sum(odds)/len(odds):.2f}</b>")
 else:out.append("ℹ️ LIVE-кэфы не обязательны и в статистику ставок без цены не входят.")
 return "\n".join(out)

def build_report_text()->str:
 rows=_today_rows();core=_core_rows(rows);fh=_engine_rows(rows,FIRST_HALF_GOAL);sh=_engine_rows(rows,SECOND_HALF_OVER15);ids=_current_live_ids();cache={};w=l=p=0;details=[];priced=0;pnl=0.0
 for r in core:
  st,score=_core_status(r,ids,cache);mark="✅" if st=="win" else "❌" if st=="loss" else "⏳";w+=st=="win";l+=st=="loss";p+=st=="pending";primary=r.get("primary") or {};odd=primary.get("odd") or r.get("odd")
  if st in {"win","loss"} and odd:
   try:o=float(odd);priced+=1;pnl+=(o-1) if st=="win" else -1
   except:pass
  label=_market_label(primary);price=f" @ {float(odd):.2f}" if odd else " · без LIVE-кэфа";details.append(f"{mark} {r.get('home')} — {r.get('away')} | {r.get('minute')}' · {label}{price} · {r.get('score_at_signal')} → {score}")
 s=w+l;lines=["📊 <b>GOOL 2.0 — ОТЧЁТ НА СЕЙЧАС</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🟡 <b>CORE · ЛУЧШАЯ СТАВКА/АНАЛИТИКА</b>",f"Сигналов: <b>{len(core)}</b> · ✅ {w} · ❌ {l} · ⏳ {p}"]
 if s:lines.append(f"🎯 Проходимость выбранного рынка: <b>{round(w/s*100)}%</b>")
 lines.append(f"💰 С подтверждённым LIVE-кэфом: <b>{priced}</b>"+(f" · P/L <b>{pnl:+.2f}u</b>" if priced else ""))
 if details:lines += ["<b>Последние CORE:</b>"]+details[-10:]
 lines.append(_section("🔵 <b>СТРАТЕГИЯ 1 · ГОЛ В 1-М ТАЙМЕ (15–25')</b>",fh))
 lines.append(_section("🟣 <b>СТРАТЕГИЯ 2 · ТБ1.5 ВО 2-М ТАЙМЕ (в перерыве)</b>",sh))
 if not rows:lines += ["","Сегодня сигналов пока нет."]
 lines += ["","<i>Прематчевые линии исключены. CORE оценивается по выбранному рынку: ТБ / ОЗ / ИТБ. LIVE-кэф — только дополнительный показатель.</i>"]
 return "\n".join(lines)
