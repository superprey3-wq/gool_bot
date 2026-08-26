"""Experimental owner-only market anomaly signal.

Independent from CORE/1T/2T. Evaluates every tracked BetB2B selection from the
remote market node and sends a text-only TEST message when a strong market
anomaly is detected. It never changes GOOL eligibility/probability.
"""
from __future__ import annotations
import json,logging,os,threading,time
from pathlib import Path
import market_node_bridge,telegram_subscribers
log=logging.getLogger("market_test_signal")
COOLDOWN=max(300,int(os.getenv("MARKET_TEST_COOLDOWN_SECONDS","1800")))
LOOKBACK=max(120,int(os.getenv("MARKET_TEST_LOOKBACK_SECONDS","600")))
MIN_SCORE=max(2,int(os.getenv("MARKET_TEST_MIN_SCORE","3")))
_LOCK=threading.Lock();_LAST_SENT={};_LAST_FINGERPRINT={}

def _journal_path():
 explicit=os.getenv("MARKET_TEST_JOURNAL","").strip()
 if explicit:return Path(explicit)
 runtime=os.getenv("RUNTIME_DATA_DIR","").strip()
 if runtime:return Path(runtime)/"market_test_signals.jsonl"
 data=Path("/data")
 if data.exists() and os.access(str(data),os.W_OK):return data/"market_test_signals.jsonl"
 return Path("market_test_signals.jsonl")
def _recent_points(row,now):
 pts=[]
 for raw in row.get("points") or []:
  try:ts=float(raw[0]);odd=float(raw[1]);line=None if raw[2] is None else float(raw[2])
  except Exception:continue
  if odd<=1 or ts<now-LOOKBACK:continue
  pts.append([ts,odd,line])
 return sorted(pts,key=lambda x:x[0])
def _label(sel):
 name=str(sel.get("name") or "").strip();group=str(sel.get("group") or "").strip();period=str(sel.get("period") or "").strip()
 line=sel.get("line");base=name or group or f"G{sel.get('group_id')} / T{sel.get('type_id')}"
 if isinstance(line,(int,float)) and str(line) not in base:base=f"{base} {line:g}"
 return f"{period} · {base}" if period and period not in {"FT","0"} else base
def _evaluate_selection(event_key,event_row,market_key,sel,now):
 pts=_recent_points(sel,now)
 if len(pts)<2:return None
 first,last=pts[0],pts[-1];elapsed=max(1.,last[0]-first[0]);delta_pp=(1/last[1]-1/first[1])*100
 line_move=0.
 if first[2] is not None and last[2] is not None:line_move=last[2]-first[2]
 # For arbitrary markets a line shift itself is meaningful but direction semantics are market-specific,
 # so it contributes to strength without pretending that up/down always means good/bad.
 pressure=delta_pp
 suspends=int(sel.get("suspends",0) or 0);reopens=int(sel.get("reopens",0) or 0);reopen_delta=float(sel.get("last_reopen_delta_pp",0) or 0)
 score=0;reasons=[]
 if abs(delta_pp)>=5:score+=2;reasons.append("strong_reprice")
 elif abs(delta_pp)>=3:score+=1;reasons.append("reprice")
 if abs(delta_pp)>=3 and elapsed<=180:score+=1;reasons.append("fast_move")
 if abs(line_move)>=0.25:score+=1;reasons.append("line_shift")
 if suspends>=1 and reopens>=1:score+=1;reasons.append("suspend_reopen")
 if suspends>=2:score+=1;reasons.append("repeated_suspend")
 if abs(reopen_delta)>=1.5:score+=1;reasons.append("reopen_reprice")
 if score<MIN_SCORE or (abs(delta_pp)<3 and abs(reopen_delta)<1.5 and abs(line_move)<0.25):return None
 fp=f"{market_key}:{round(last[1],3)}:{last[2]}:{suspends}:{reopens}"
 return {"key":event_key,"market_key":market_key,"home":event_row.get("home") or "?","away":event_row.get("away") or "?","event_id":event_row.get("event_id"),"market":_label(sel),"score":score,"reasons":reasons,"delta_pp":round(delta_pp,2),"elapsed":int(elapsed),"start_odds":round(first[1],3),"last_odds":round(last[1],3),"start_line":first[2],"last_line":last[2],"line_move":round(line_move,2),"suspends":suspends,"reopens":reopens,"reopen_delta_pp":round(reopen_delta,2),"fingerprint":fp,"created_ts":now}
def _best_for_event(key,row,now):
 candidates=[]
 for mk,sel in (row.get("markets") or {}).items():
  if isinstance(sel,dict):
   sig=_evaluate_selection(key,row,mk,sel,now)
   if sig:candidates.append(sig)
 if not candidates:return None
 return max(candidates,key=lambda s:(s["score"],abs(s["delta_pp"]),abs(s["reopen_delta_pp"]),abs(s["line_move"])))
def _message(sig):
 level="EXTREME" if sig["score"]>=5 else "STRONG"
 parts=["🧪 <b>ТЕСТ</b>",f"⚽ <b>{sig['home']} — {sig['away']}</b>",f"Рынок: <b>{sig['market']}</b>",f"Кэф: <b>{sig['start_odds']} → {sig['last_odds']}</b> · Δ вероятности {sig['delta_pp']:+.2f} п.п. · {sig['elapsed']} сек"]
 if sig.get("start_line") is not None and sig.get("last_line") is not None and sig["start_line"]!=sig["last_line"]:parts.append(f"Линия: <b>{sig['start_line']:g} → {sig['last_line']:g}</b>")
 if sig["suspends"] or sig["reopens"]:parts.append(f"Блокировки: <b>{sig['suspends']}</b> · reopen: <b>{sig['reopens']}</b> · repricing {sig['reopen_delta_pp']:+.2f} п.п.")
 parts += [f"Уровень: <b>{level} · {sig['score']}</b>","<i>Экспериментальный рыночный сигнал. Не влияет на CORE / 1T / 2T.</i>"]
 return "\n".join(parts)
def _write_journal(sig,delivered):
 record=dict(sig);record["delivered"]=bool(delivered);record["kind"]="market_test"
 try:
  p=_journal_path();p.parent.mkdir(parents=True,exist_ok=True)
  with p.open("a",encoding="utf-8") as fh:fh.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
 except Exception as exc:log.warning("MARKET_TEST journal failed: %s",exc)
def scan_once():
 now=time.time()
 with market_node_bridge.LOCK:rows={k:dict(v) for k,v in market_node_bridge.REMOTE.items()}
 if not rows:return 0
 owner=telegram_subscribers._owner_chat_id()
 if not owner:return 0
 sent=0
 for key,row in rows.items():
  sig=_best_for_event(key,row,now)
  if not sig:continue
  dedupe_key=f"{key}:{sig['market_key']}"
  with _LOCK:
   if now-_LAST_SENT.get(dedupe_key,0)<COOLDOWN and _LAST_FINGERPRINT.get(dedupe_key)==sig["fingerprint"]:continue
   _LAST_SENT[dedupe_key]=now;_LAST_FINGERPRINT[dedupe_key]=sig["fingerprint"]
  delivered=telegram_subscribers._post_message(owner,_message(sig));_write_journal(sig,delivered)
  if delivered:sent+=1;log.info("MARKET_TEST_SENT key=%s market=%s score=%d delta=%+.2f",key,sig["market"],sig["score"],sig["delta_pp"])
 return sent
