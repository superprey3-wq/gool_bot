"""Experimental owner-only market anomaly signal.

Independent from CORE/1T/2T. The backup market node keeps the heavy all-market
history and exposes only compact anomaly candidates. The main server only pulls
those candidates, de-duplicates them and sends owner-only TEST messages.
"""
from __future__ import annotations
import json,logging,os,threading,time
from pathlib import Path
import requests
import market_node_bridge,telegram_subscribers
log=logging.getLogger("market_test_signal")
COOLDOWN=max(300,int(os.getenv("MARKET_TEST_COOLDOWN_SECONDS","1800")))
_LOCK=threading.Lock();_LAST_SENT={};_LAST_FINGERPRINT={}

def _journal_path():
 explicit=os.getenv("MARKET_TEST_JOURNAL","").strip()
 if explicit:return Path(explicit)
 runtime=os.getenv("RUNTIME_DATA_DIR","").strip()
 if runtime:return Path(runtime)/"market_test_signals.jsonl"
 data=Path("/data")
 if data.exists() and os.access(str(data),os.W_OK):return data/"market_test_signals.jsonl"
 return Path("market_test_signals.jsonl")

def _message(sig):
 level="EXTREME" if int(sig.get("score",0) or 0)>=5 else "STRONG"
 parts=[
  "🧪 <b>ТЕСТ</b>",
  f"⚽ <b>{sig.get('home') or '?'} — {sig.get('away') or '?'}</b>",
  f"Рынок: <b>{sig.get('market') or '—'}</b>",
  f"Кэф: <b>{sig.get('start_odds','—')} → {sig.get('last_odds','—')}</b> · Δ вероятности {float(sig.get('delta_pp',0) or 0):+.2f} п.п. · {int(sig.get('elapsed',0) or 0)} сек",
 ]
 a=sig.get("start_line");b=sig.get("last_line")
 if a is not None and b is not None and a!=b:parts.append(f"Линия: <b>{a} → {b}</b>")
 susp=int(sig.get("suspends",0) or 0);reop=int(sig.get("reopens",0) or 0)
 if susp or reop:parts.append(f"Блокировки: <b>{susp}</b> · reopen: <b>{reop}</b> · repricing {float(sig.get('reopen_delta_pp',0) or 0):+.2f} п.п.")
 parts += [f"Уровень: <b>{level} · {int(sig.get('score',0) or 0)}</b>","<i>Экспериментальный рыночный сигнал. Не влияет на CORE / 1T / 2T.</i>"]
 return "\n".join(parts)

def _write_journal(sig,delivered):
 record=dict(sig);record["delivered"]=bool(delivered);record["kind"]="market_test"
 try:
  p=_journal_path();p.parent.mkdir(parents=True,exist_ok=True)
  with p.open("a",encoding="utf-8") as fh:fh.write(json.dumps(record,ensure_ascii=False,separators=(",",":"))+"\n")
 except Exception as exc:log.warning("MARKET_TEST journal failed: %s",exc)

def _fetch_anomalies():
 url=market_node_bridge.URL
 if not url:return []
 headers={"Authorization":"Bearer "+market_node_bridge.SECRET} if market_node_bridge.SECRET else {}
 try:
  r=requests.get(url+"/anomalies",headers=headers,timeout=10)
  if r.status_code==401:raise RuntimeError("401 unauthorized: MARKET_NODE_SECRET mismatch")
  r.raise_for_status();body=r.json();signals=body.get("signals") or []
  if not isinstance(signals,list):raise RuntimeError("invalid anomalies payload")
  log.info("MARKET_TEST_PULL candidates=%d",len(signals));return [x for x in signals if isinstance(x,dict)]
 except Exception as exc:
  log.warning("MARKET_TEST_PULL_FAIL %s: %s",type(exc).__name__,exc);return []

def scan_once():
 signals=_fetch_anomalies()
 if not signals:return 0
 owner=telegram_subscribers._owner_chat_id()
 if not owner:return 0
 now=time.time();sent=0
 for sig in signals:
  dedupe_key=f"{sig.get('key')}:{sig.get('market_key')}";fp=str(sig.get("fingerprint") or "")
  with _LOCK:
   if now-_LAST_SENT.get(dedupe_key,0)<COOLDOWN and _LAST_FINGERPRINT.get(dedupe_key)==fp:continue
   _LAST_SENT[dedupe_key]=now;_LAST_FINGERPRINT[dedupe_key]=fp
  delivered=telegram_subscribers._post_message(owner,_message(sig));_write_journal(sig,delivered)
  if delivered:
   sent+=1;log.info("MARKET_TEST_SENT key=%s market=%s score=%s delta=%+.2f",sig.get("key"),sig.get("market"),sig.get("score"),float(sig.get("delta_pp",0) or 0))
  else:log.warning("MARKET_TEST_DELIVERY_FAIL key=%s",sig.get("key"))
 return sent
