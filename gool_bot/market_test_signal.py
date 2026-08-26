"""Owner-only automatic sharp market-movement alerts."""
from __future__ import annotations
import json,logging,os,re,threading,time
from pathlib import Path
import requests
import market_node_bridge,telegram_subscribers
log=logging.getLogger("market_test_signal")
_LOCK=threading.Lock();_LAST_SENT={};_LAST_FINGERPRINT={};_PRIMED=False

def _journal_path():
 explicit=os.getenv("MARKET_TEST_JOURNAL","").strip()
 if explicit:return Path(explicit)
 runtime=os.getenv("RUNTIME_DATA_DIR","").strip()
 if runtime:return Path(runtime)/"market_test_signals.jsonl"
 data=Path("/data")
 if data.exists() and os.access(str(data),os.W_OK):return data/"market_test_signals.jsonl"
 return Path("market_test_signals.jsonl")

def _num(v,digits=2):
 try:return f"{float(v):.{digits}f}"
 except Exception:return "—"
def _prob(odd):
 try:return 100.0/float(odd) if float(odd)>1 else None
 except Exception:return None
def _market_name(sig):
 raw=" ".join(str(sig.get("market") or "").split());line=sig.get("last_line")
 try:ti=int(sig.get("type_id"))
 except Exception:
  m=re.search(r"\bT(\d+)\b",raw,re.I);ti=int(m.group(1)) if m else None
 try:gi=int(sig.get("group_id"))
 except Exception:
  m=re.search(r"\bG(\d+)\b",raw,re.I);gi=int(m.group(1)) if m else None
 ln=_num(line,1).rstrip("0").rstrip(".") if line is not None else "?"
 if gi==4 and ti==9:return f"ТБ {ln}"
 if gi==4 and ti==10:return f"ТМ {ln}"
 if ti==11:return f"ИТ1М {ln}"
 if ti==12:return f"ИТ1Б {ln}"
 if ti==13:return f"ИТ2М {ln}"
 if ti==14:return f"ИТ2Б {ln}"
 if gi==1 and ti==1:return "П1"
 if gi==1 and ti==3:return "П2"
 if ti==7:return f"Ф1 {ln}"
 if ti==8:return f"Ф2 {ln}"
 return raw or "рынок"
def _meaning(delta,name):
 if "ТБ" in name or "ИТ1Б" in name or "ИТ2Б" in name:return "🟢 Рынок резко сильнее ждёт голы" if delta>0 else "🔴 Рынок резко уходит от голов"
 if "ТМ" in name or "ИТ1М" in name or "ИТ2М" in name:return "🔴 Рынок резко сильнее ждёт низ" if delta>0 else "🟢 Рынок резко уходит от низа"
 return "📈 Вероятность этого исхода резко выросла" if delta>0 else "📉 Вероятность этого исхода резко снизилась"
def _message(sig):
 delta=float(sig.get("delta_pp",0) or 0);name=_market_name(sig);old=sig.get("start_odds");new=sig.get("last_odds");p0=_prob(old);p1=_prob(new);elapsed=max(1,int(sig.get("elapsed",0) or 0));arrow="↓" if delta>0 else "↑" if delta<0 else "→"
 title="🚨 <b>РЕЗКОЕ ДВИЖЕНИЕ РЫНКА</b>" if delta>=0 else "🚨 <b>РЫНОК РЕЗКО ОХЛАДЕЛ</b>"
 parts=[title,f"⚽ <b>{sig.get('home') or '?'} — {sig.get('away') or '?'}</b>",f"📊 <b>{name}</b>",f"Кэф: <b>{_num(old)} → {_num(new)} {arrow}</b>"]
 if p0 is not None and p1 is not None:parts.append(f"Вероятность: <b>{p0:.0f}% → {p1:.0f}%</b>")
 parts.append(f"Δ <b>{delta:+.2f} п.п.</b> за <b>{elapsed} сек</b>")
 a=sig.get("start_line");b=sig.get("last_line")
 if a is not None and b is not None and a!=b:parts.append(f"Линия: <b>{a} → {b}</b>")
 parts.append(_meaning(delta,name))
 susp=int(sig.get("suspends",0) or 0);reop=int(sig.get("reopens",0) or 0)
 if susp or reop:parts.append(f"⚡ Букмекер: блокировок {susp} · reopen {reop}")
 parts.append("<i>Автосигнал только владельцу · новое резкое изменение рынка.</i>")
 return "\n".join(parts)

def _write_journal(sig,delivered):
 record=dict(sig);record["delivered"]=bool(delivered);record["kind"]="market_sharp_move"
 try:
  p=_journal_path();p.parent.mkdir(parents=True,exist_ok=True)
  with p.open("a",encoding="utf-8") as fh:fh.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
 except Exception as exc:log.warning("MARKET_ALERT journal failed: %s",exc)
def _fetch_anomalies():
 url=market_node_bridge.URL
 if not url:return []
 headers={"Authorization":"Bearer "+market_node_bridge.SECRET} if market_node_bridge.SECRET else {}
 try:
  r=requests.get(url+"/anomalies",headers=headers,timeout=10)
  if r.status_code==401:raise RuntimeError("401 unauthorized: MARKET_NODE_SECRET mismatch")
  r.raise_for_status();body=r.json();signals=body.get("signals") or body.get("anomalies") or []
  if not isinstance(signals,list):raise RuntimeError("invalid anomalies payload")
  log.info("MARKET_ALERT_PULL candidates=%d",len(signals));return [x for x in signals if isinstance(x,dict)]
 except Exception as exc:log.warning("MARKET_ALERT_PULL_FAIL %s: %s",type(exc).__name__,exc);return []
def _id(sig):return f"{sig.get('key')}:{sig.get('market_key')}"
def _sharp(sig):
 try:d=abs(float(sig.get("delta_pp",0) or 0));elapsed=int(sig.get("elapsed",0) or 0);lm=abs(float(sig.get("line_move",0) or 0));rd=abs(float(sig.get("reopen_delta_pp",0) or 0));s=int(sig.get("suspends",0) or 0);r=int(sig.get("reopens",0) or 0)
 except Exception:return False
 return d>=8 or (d>=5 and elapsed<=180) or (d>=4 and (lm>=.25 or (s>=1 and r>=1))) or (rd>=3 and s>=1 and r>=1)
def scan_once():
 global _PRIMED
 signals=[s for s in _fetch_anomalies() if _sharp(s)]
 if not signals:return 0
 owner=telegram_subscribers._owner_chat_id()
 if not owner:return 0
 now=time.time()
 with _LOCK:
  if not _PRIMED:
   for sig in signals:_LAST_FINGERPRINT[_id(sig)]=str(sig.get("fingerprint") or "")
   _PRIMED=True;log.info("MARKET_ALERT_BASELINE candidates=%d sent=0",len(signals));return 0
 sent=0
 for sig in signals:
  key=_id(sig);fp=str(sig.get("fingerprint") or "")
  with _LOCK:
   if _LAST_FINGERPRINT.get(key)==fp:continue
   _LAST_FINGERPRINT[key]=fp
   if now-_LAST_SENT.get(key,0)<120:continue
   _LAST_SENT[key]=now
  delivered=telegram_subscribers._post_message(owner,_message(sig));_write_journal(sig,delivered)
  if delivered:sent+=1;log.info("MARKET_ALERT_SENT key=%s market=%s delta=%+.2f",sig.get("key"),sig.get("market"),float(sig.get("delta_pp",0) or 0))
 return sent
