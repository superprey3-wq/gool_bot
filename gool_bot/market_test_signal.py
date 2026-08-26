"""Owner-only automatic sharp market-movement alerts: top 5 LIVE matches only."""
from __future__ import annotations
import json,logging,os,re,threading,time
from pathlib import Path
import requests
import market_node_bridge,telegram_subscribers
log=logging.getLogger("market_test_signal")
_LOCK=threading.Lock();_ALERTED_MATCHES=set();_BASELINE=set();_PRIMED=False
TOP_MATCHES=5

def _journal_path():
 runtime=os.getenv("RUNTIME_DATA_DIR","").strip();return Path(runtime)/"market_test_signals.jsonl" if runtime else Path("/data/market_test_signals.jsonl") if Path("/data").exists() else Path("market_test_signals.jsonl")
def _num(v,d=2):
 try:return f"{float(v):.{d}f}"
 except Exception:return "—"
def _prob(v):
 try:return 100/float(v) if float(v)>1 else None
 except Exception:return None
def _market_name(s):
 raw=str(s.get("market") or "");ln=s.get("last_line")
 try:ti=int(s.get("type_id"))
 except Exception:
  m=re.search(r"\bT(\d+)\b",raw,re.I);ti=int(m.group(1)) if m else None
 try:gi=int(s.get("group_id"))
 except Exception:
  m=re.search(r"\bG(\d+)\b",raw,re.I);gi=int(m.group(1)) if m else None
 l=_num(ln,1).rstrip("0").rstrip(".") if ln is not None else "?"
 return ({(4,9):f"ТБ {l}",(4,10):f"ТМ {l}"}.get((gi,ti)) or {11:f"ИТ1М {l}",12:f"ИТ1Б {l}",13:f"ИТ2М {l}",14:f"ИТ2Б {l}",7:f"Ф1 {l}",8:f"Ф2 {l}"}.get(ti) or ("П1" if gi==1 and ti==1 else "П2" if gi==1 and ti==3 else raw or "рынок"))
def _meaning(d,n):
 if "ТБ" in n:return "🟢 Рынок резко сильнее ждёт голы" if d>0 else "🔴 Рынок резко уходит от голов"
 if "ТМ" in n:return "🔴 Рынок резко сильнее ждёт низ" if d>0 else "🟢 Рынок резко уходит от низа"
 return "📈 Вероятность исхода резко выросла" if d>0 else "📉 Вероятность исхода резко снизилась"
def _message(s):
 d=float(s.get("delta_pp",0) or 0);n=_market_name(s);a=s.get("start_odds");b=s.get("last_odds");p0=_prob(a);p1=_prob(b);sec=max(1,int(s.get("elapsed",0) or 0));arrow="↓" if d>0 else "↑"
 parts=["🚨 <b>ТОП-ПРОГРУЗ LIVE</b>",f"⚽ <b>{s.get('home') or '?'} — {s.get('away') or '?'}</b>",f"📊 <b>{n}</b>",f"Кэф: <b>{_num(a)} → {_num(b)} {arrow}</b>"]
 if p0 is not None and p1 is not None:parts.append(f"Вероятность: <b>{p0:.0f}% → {p1:.0f}%</b>")
 parts.extend([f"Δ <b>{d:+.2f} п.п.</b> за <b>{sec} сек</b>",_meaning(d,n),"<i>Только LIVE · только топ-5 сильнейших · один автосигнал на матч.</i>"]);return "\n".join(parts)
def _write(s,ok):
 try:
  p=_journal_path();p.parent.mkdir(parents=True,exist_ok=True);r=dict(s,delivered=bool(ok),kind="market_top5_live");p.open("a",encoding="utf-8").write(json.dumps(r,ensure_ascii=False)+"\n")
 except Exception as e:log.warning("MARKET_ALERT journal: %s",e)
def _fetch():
 if not market_node_bridge.URL:return []
 try:
  h={"Authorization":"Bearer "+market_node_bridge.SECRET} if market_node_bridge.SECRET else {};r=requests.get(market_node_bridge.URL+"/anomalies",headers=h,timeout=10);r.raise_for_status();x=r.json();return [z for z in (x.get("signals") or x.get("anomalies") or []) if isinstance(z,dict)]
 except Exception as e:log.warning("MARKET_ALERT_PULL_FAIL %s",e);return []
def _sharp(s):
 try:d=abs(float(s.get("delta_pp",0) or 0));sec=int(s.get("elapsed",0) or 0);return d>=8 or (d>=5 and sec<=180)
 except Exception:return False
def _live(s):
 # Node anomalies are generated from its current LIVE snapshot. Reject explicit
 # non-live/pre-match/final flags if a node version supplies them.
 status=str(s.get("status") or s.get("state") or "live").casefold()
 if any(x in status for x in ("prematch","pre-match","scheduled","finished","final","ended")):return False
 try:m=int(s.get("minute") or s.get("match_minute") or 1);return 0<m<=130
 except Exception:return True
def _match_id(s):return str(s.get("key") or f"{s.get('home')}|{s.get('away')}")
def scan_once():
 global _PRIMED
 signals=[s for s in _fetch() if _live(s) and _sharp(s)]
 # One best market per match, then only five strongest matches in this scan.
 best={}
 for s in signals:
  k=_match_id(s);strength=abs(float(s.get("delta_pp",0) or 0));
  if k not in best or strength>best[k][0]:best[k]=(strength,s)
 top=[x[1] for x in sorted(best.values(),key=lambda z:z[0],reverse=True)[:TOP_MATCHES]]
 owner=telegram_subscribers._owner_chat_id()
 if not owner:return 0
 with _LOCK:
  if not _PRIMED:
   _BASELINE.update(_match_id(s) for s in top);_PRIMED=True;log.info("MARKET_ALERT_BASELINE top=%d sent=0",len(top));return 0
 sent=0
 for s in top:
  k=_match_id(s)
  with _LOCK:
   if k in _BASELINE or k in _ALERTED_MATCHES:continue
   _ALERTED_MATCHES.add(k)
  ok=telegram_subscribers._post_message(owner,_message(s));_write(s,ok)
  if ok:sent+=1;log.info("MARKET_TOP5_LIVE_SENT match=%s delta=%+.2f",k,float(s.get("delta_pp",0) or 0))
  else:
   with _LOCK:_ALERTED_MATCHES.discard(k)
 return sent
