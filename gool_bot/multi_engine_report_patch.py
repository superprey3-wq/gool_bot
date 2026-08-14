"""Make /report visibly separate CORE, HT HUNTER and LATE RISK."""
from datetime import datetime
import report_now
from signal_journal import all_signals
from multi_engine import HT_HUNTER,LATE_RISK
_orig=report_now.build_report_text

def _today_engine_rows(engine):
 today=datetime.now(report_now.MOSCOW).date();out=[]
 for r in all_signals():
  if r.get("engine")!=engine:continue
  try:d=datetime.fromtimestamp(int(r.get("created_ts",0)),report_now.MOSCOW).date()
  except:continue
  if d==today:out.append(r)
 return out

def _section(title,rows):
 wins=sum(str(r.get("result")) in {"+","win","WIN"} for r in rows);loss=sum(str(r.get("result")) in {"-","loss","LOSS"} for r in rows);wait=len(rows)-wins-loss;settled=wins+loss;rate=round(wins/settled*100) if settled else 0
 odds=[]
 for r in rows:
  try:
   o=float(r.get("odd",0));odds.append(o) if o>1 else None
  except:pass
 lines=["",title,f"Сигналов: <b>{len(rows)}</b>",f"✅ Зашло: <b>{wins}</b> · ❌ Не зашло: <b>{loss}</b> · ⏳ В игре: <b>{wait}</b>"]
 if settled:lines.append(f"🎯 Проходимость: <b>{rate}%</b>")
 if odds:lines.append(f"💰 Средний LIVE-кэф: <b>{sum(odds)/len(odds):.2f}</b>")
 for r in rows[-6:]:
  mark="✅" if str(r.get("result"))=="+" else "❌" if str(r.get("result"))=="-" else "⏳";lines.append(f"{mark} {r.get('home')} — {r.get('away')} | {r.get('minute')}' {r.get('score_at_signal')}")
 return "\n".join(lines)

def build_report_text():
 base=_orig().replace("🔴 <b>LIVE</b>","🟡 <b>ГЛАВНЫЕ СИГНАЛЫ · GOOL CORE</b>",1)
 return base+"\n"+_section("🔵 <b>ПЕРВЫЙ ТАЙМ · HT HUNTER</b>",_today_engine_rows(HT_HUNTER))+"\n"+_section("🔴 <b>ВТОРОЙ ТАЙМ · LATE RISK</b>",_today_engine_rows(LATE_RISK))
report_now.build_report_text=build_report_text
