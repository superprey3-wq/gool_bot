"""GOOL 2.0 historical analysis: CORE exact market + two auxiliary strategies."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from signal_journal import all_signals
from report_now import _current_live_ids,_market_hit,_market_label
from live_engine import fetch_summary
from daily_report import _score_from_summary
from multi_engine import FIRST_HALF_GOAL,SECOND_HALF_OVER15
MOSCOW=ZoneInfo("Europe/Moscow");WIN={"+","win","won"};LOSS={"-","loss","lost"}

def _all():return [r for r in all_signals() if r.get("kind")=="live"]
def _core(rows):return [r for r in rows if str(r.get("engine") or "core") not in {FIRST_HALF_GOAL,SECOND_HALF_OVER15} and str(r.get("reason") or "signal") in {"signal","reentry"}]
def _num(r,*keys):
 for k in keys:
  try:
   if r.get(k) is not None:return float(r.get(k))
  except:pass
 return None

def _bucket_minute(m):
 m=int(m or 0)
 if m<=20:return "10–20'"
 if m<=40:return "21–40'"
 if m<=60:return "41–60'"
 if m<=74:return "61–74'"
 return "75+'"
def _bucket_rating(v):
 if v is None:return "нет данных"
 if v<70:return "<70"
 if v<80:return "70–79"
 if v<90:return "80–89"
 return "90+"
def _market_bucket(r):
 p=r.get("primary") or {};k=str(p.get("market_type") or p.get("market") or "NONE").upper()
 return "ТБ матча" if k in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER"} else "ОЗ" if k=="BTTS" else "ИТБ хозяев" if k=="TEAM_TOTAL_HOME" else "ИТБ гостей" if k=="TEAM_TOTAL_AWAY" else "Без конкретного рынка"

def _settled_core(rows):
 ids=_current_live_ids();cache={};out=[]
 for r in _core(rows):
  st=str(r.get("result") or "pending").lower()
  if st in WIN:out.append((r,True,str(r.get("final_score") or "✓")));continue
  if st in LOSS:out.append((r,False,str(r.get("final_score") or "—")));continue
  eid=str(r.get("event_id") or "")
  if ids is not None and eid in ids:continue
  if eid not in cache:
   try:cache[eid]=fetch_summary(eid)
   except:cache[eid]=None
  if not cache[eid]:continue
  try:h,a,_,_=_score_from_summary(cache[eid]);score=f"{h}:{a}"
  except:continue
  hit=_market_hit(r.get("primary"),score)
  if hit is not None:out.append((r,bool(hit),score))
 return out

def _engine_items(rows,e):
 out=[]
 for r in rows:
  if str(r.get("engine") or "")!=e:continue
  st=str(r.get("result") or "pending").lower()
  if st in WIN:out.append((r,True,str(r.get("final_score") or "✓")))
  elif st in LOSS:out.append((r,False,str(r.get("final_score") or "—")))
 return out

def _groups(items,key):
 d=defaultdict(lambda:[0,0])
 for r,w,_ in items:k=key(r);d[k][0]+=1;d[k][1]+=int(w)
 return d
def _fmt(title,d,order=None):
 out=[f"<b>{title}</b>"]
 for k in order or list(d):
  if k not in d:continue
  n,w=d[k];out.append(f"• {k}: <b>{w}/{n} · {round(100*w/n) if n else 0}%</b>")
 return out
def _summary(label,items):
 n=len(items);w=sum(int(x[1]) for x in items);return f"• {label}: <b>{n}</b> · ✅ {w} · ❌ {n-w} · <b>{round(100*w/n) if n else 0}%</b>"
def _engine_section(title,items):
 out=["",title]
 if not items:return out+["• Пока нет закрытых сигналов."]
 out.append(_summary("Закрыто",items));out += [""]+_fmt("По рейтингу",_groups(items,lambda r:_bucket_rating(_num(r,"strategy_score","master"))),["<70","70–79","80–89","90+","нет данных"])
 return out

def build_analysis_text():
 rows=_all();core=_settled_core(rows);cw=sum(int(w) for _,w,_ in core);priced=[];pnl=0.0
 for r,w,_ in core:
  p=r.get("primary") or {};o=p.get("odd") or r.get("odd")
  try:o=float(o)
  except:continue
  if o>1:priced.append((r,w,o));pnl+=(o-1) if w else -1
 lines=["🧠 <b>GOOL 2.0 — АНАЛИЗ ЗА ВСЁ ВРЕМЯ</b>",f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}","","🟡 <b>CORE · ВЫБРАННЫЙ РЫНОК</b>",f"Закрыто: <b>{len(core)}</b> · ✅ {cw} · ❌ {len(core)-cw} · <b>{round(100*cw/len(core)) if core else 0}%</b>",f"💰 С подтверждённым LIVE-кэфом: <b>{len(priced)}</b>"+(f" · P/L <b>{pnl:+.2f}u</b>" if priced else "")]
 if core:
  first=[x for x in core if str(x[0].get("reason") or "signal")=="signal"];re=[x for x in core if str(x[0].get("reason") or "signal")=="reentry"]
  lines += ["","♻️ <b>Тип входа</b>",_summary("Первичный",first),_summary("Повторный",re)]
  lines += [""]+_fmt("🎯 По рынку",_groups(core,_market_bucket),["ТБ матча","ОЗ","ИТБ хозяев","ИТБ гостей","Без конкретного рынка"])
  lines += [""]+_fmt("⏱ По минуте",_groups(core,lambda r:_bucket_minute(r.get("minute"))),["10–20'","21–40'","41–60'","61–74'","75+'"]) 
  lines += [""]+_fmt("⭐ По MASTER",_groups(core,lambda r:_bucket_rating(_num(r,"master"))),["<70","70–79","80–89","90+","нет данных"])
  lines += ["","<b>Последние закрытые CORE:</b>"]
  for r,w,score in core[-8:]:
   p=r.get("primary") or {};o=p.get("odd") or r.get("odd");price=f" @{float(o):.2f}" if o else " без кэфа";lines.append(f"{'✅' if w else '❌'} {r.get('home')} — {r.get('away')} · {_market_label(p)}{price} · {score}")
 fh=_engine_items(rows,FIRST_HALF_GOAL);sh=_engine_items(rows,SECOND_HALF_OVER15)
 lines += _engine_section("🔵 <b>СТРАТЕГИЯ 1 · ГОЛ В 1-М ТАЙМЕ (15–25')</b>",fh)
 lines += _engine_section("🟣 <b>СТРАТЕГИЯ 2 · ТБ1.5 ВО 2-М ТАЙМЕ (ПЕРЕРЫВ)</b>",sh)
 lines += ["","<i>Аналитические сигналы без свежего LIVE-кэфа учитываются в точности модели, но не в P/L. Прематчевые линии исключены.</i>"]
 return "\n".join(lines)
