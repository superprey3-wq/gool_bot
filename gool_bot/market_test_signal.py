"""Owner-only sharp full-match total alerts: LIVE + starts within two hours."""
from __future__ import annotations
import logging,re,threading,time,requests
import market_node_bridge,telegram_subscribers
from prematch_market_lab import fetch_odds,normalize_odds
log=logging.getLogger("market_test_signal")
_LOCK=threading.Lock();_ALERTED=set();_BASELINE=set();_PRIMED=False;TOP_MATCHES=5;WINDOW=7200
_PM_LAST=0.0;_PM_INTERVAL=60;_PM_STATE={}

def _num(v,d=2):
 try:return f"{float(v):.{d}f}"
 except Exception:return "—"
def _prob(v):
 try:return 100/float(v) if float(v)>1 else None
 except Exception:return None
def _type(s):
 try:return int(s.get("type_id"))
 except Exception:
  m=re.search(r"\bT\s*(\d+)\b",str(s.get("market") or ""),re.I);return int(m.group(1)) if m else None
def _group(s):
 try:return int(s.get("group_id"))
 except Exception:
  m=re.search(r"\bG\s*(\d+)\b",str(s.get("market") or ""),re.I);return int(m.group(1)) if m else None
def _total(s):
 ti,gi=_type(s),_group(s)
 if ti in (9,10) and gi==4 and s.get("last_line") is not None:return True
 raw=str(s.get("market") or "").casefold();textual=("total" in raw or "over_under" in raw or "over/under" in raw or "тотал" in raw) and not any(x in raw for x in ("team total","individual","1st half","first half","2nd half","second half","ит1","ит2"))
 return textual and any(x in raw for x in ("over","under","тб","тм")) and s.get("last_line") is not None
def _is_over(s):
 ti=_type(s)
 if ti in (9,10):return ti==9
 raw=(str(s.get("selection") or "")+" "+str(s.get("market") or "")).casefold();return "over" in raw or "тб" in raw
def _name(s):
 ln=_num(s.get("last_line"),1).rstrip("0").rstrip(".");return ("ТБ " if _is_over(s) else "ТМ ")+ln
def _sharp(s):
 try:d=abs(float(s.get("delta_pp",0) or 0));sec=int(s.get("elapsed",0) or 0);return d>=8 or (d>=5 and sec<=180)
 except Exception:return False
def _eligible_time(s):
 status=str(s.get("status") or s.get("state") or "").casefold()
 if any(x in status for x in ("finished","final","ended")):return False
 if "live" in status or str(s.get("is_live") or "").casefold() in ("1","true","yes"):return True
 try:
  if int(s.get("minute") or s.get("match_minute") or 0)>0:return True
 except Exception:pass
 try:start=float(s.get("start_ts") or s.get("start_time") or 0)
 except Exception:start=0
 return 0<=start-time.time()<=WINDOW if start else True
def _time_label(s):
 try:
  m=int(s.get("minute") or s.get("match_minute") or 0)
  if m>0:return f"LIVE · {m}'"
 except Exception:pass
 try:
  st=float(s.get("start_ts") or 0)
  if st>time.time():return f"старт через {max(1,int((st-time.time())/60))} мин"
 except Exception:pass
 return "LIVE"
def _meaning(s,d):
 if _is_over(s):return "🟢 рынок резко сильнее ждёт голы" if d>0 else "🔴 рынок резко уходит от голов"
 return "🔴 рынок резко сильнее ждёт низ" if d>0 else "🟢 рынок резко уходит от низа"
def _message(s):
 d=float(s.get("delta_pp",0) or 0);a=s.get("start_odds");b=s.get("last_odds");p0=_prob(a);p1=_prob(b);sec=max(1,int(s.get("elapsed",0) or 0));arrow="↓" if d>0 else "↑" if d<0 else "→"
 parts=["🚨 <b>ТОП-ПРОГРУЗ ТОТАЛА</b>",f"⚽ <b>{s.get('home') or '?'} — {s.get('away') or '?'}</b>",f"⏱ {_time_label(s)}",f"📊 <b>{_name(s)}</b>","","<b>БЫЛО → СТАЛО</b>",f"Кэф: <b>{_num(a)} → {_num(b)} {arrow}</b>"]
 if p0 is not None and p1 is not None:parts.append(f"Вероятность: <b>{p0:.0f}% → {p1:.0f}%</b>")
 parts.extend([f"Изменение: <b>{d:+.2f} п.п.</b> за <b>{sec} сек</b>","",_meaning(s,d),"<i>Только тоталы матча ТБ/ТМ · LIVE или старт ≤2ч · топ-5 · один сигнал на матч.</i>"]);return "\n".join(parts)
def _fetch_live():
 if not market_node_bridge.URL:return []
 try:
  h={"Authorization":"Bearer "+market_node_bridge.SECRET} if market_node_bridge.SECRET else {};r=requests.get(market_node_bridge.URL+"/anomalies",headers=h,timeout=10);r.raise_for_status();x=r.json();return [z for z in (x.get("signals") or x.get("anomalies") or []) if isinstance(z,dict)]
 except Exception as e:log.warning("MARKET_ALERT_PULL_FAIL %s",e);return []
def _fixtures():
 if not market_node_bridge.URL:return []
 try:
  h={"Authorization":"Bearer "+market_node_bridge.SECRET} if market_node_bridge.SECRET else {};r=requests.get(market_node_bridge.URL+"/fixtures/today",headers=h,timeout=10);r.raise_for_status();return [x for x in (r.json().get("fixtures") or []) if isinstance(x,dict)]
 except Exception as e:log.warning("MARKET_PREMATCH_FIXTURES_FAIL %s",e);return []
def _pm_rows():
 global _PM_LAST
 now=time.time()
 if now-_PM_LAST<_PM_INTERVAL:return []
 _PM_LAST=now;out=[];near=[]
 for f in _fixtures():
  try:st=float(f.get("start_ts") or 0)
  except Exception:continue
  if 0<st-now<=WINDOW:near.append(f)
 # Cap requests defensively; closest starts first.
 near.sort(key=lambda x:float(x.get("start_ts") or 0));near=near[:20]
 for f in near:
  eid=str(f.get("event_id") or f.get("fs_id") or "")
  if not eid:continue
  rows=normalize_odds(fetch_odds(eid))
  for q in rows:
   market=str(q.get("market") or "").upper();scope=str(q.get("scope") or "").upper();sel=str(q.get("selection") or "").upper();line=q.get("line");odd=q.get("current")
   if scope not in ("FULL_TIME","FULLTIME","FT","MATCH","0",""):continue
   if not ("OVER" in market or "TOTAL" in market):continue
   if sel not in ("OVER","UNDER","O","U"):continue
   try:odd=float(odd);float(line)
   except Exception:continue
   key=f"{eid}|{market}|{sel}|{line}|{q.get('bookmaker_id')}";prev=_PM_STATE.get(key);_PM_STATE[key]=(now,odd)
   if not prev or now-prev[0]<20:continue
   delta=(1/odd-1/prev[1])*100;elapsed=int(now-prev[0])
   out.append({"key":"pm:"+eid,"market_key":key,"home":f.get("home"),"away":f.get("away"),"event_id":eid,"market":f"TOTAL {sel}","selection":sel,"last_line":float(line),"start_odds":prev[1],"last_odds":odd,"delta_pp":round(delta,2),"elapsed":elapsed,"start_ts":float(f.get("start_ts") or 0),"status":"prematch"})
 log.info("MARKET_PREMATCH_SCAN fixtures=%d movements=%d",len(near),len(out));return out
def _mid(s):return str(s.get("key") or f"{s.get('home')}|{s.get('away')}")
def scan_once():
 global _PRIMED
 live=_fetch_live();prematch=_pm_rows();raw=live+prematch;totals=[s for s in raw if _total(s)];sharp=[s for s in totals if _sharp(s)];signals=[s for s in sharp if _eligible_time(s)]
 log.info("MARKET_TOTAL_FILTER live=%d prematch=%d totals=%d sharp=%d eligible=%d",len(live),len(prematch),len(totals),len(sharp),len(signals))
 best={}
 for s in signals:
  k=_mid(s);strength=abs(float(s.get("delta_pp",0) or 0))
  if k not in best or strength>best[k][0]:best[k]=(strength,s)
 top=[v[1] for v in sorted(best.values(),key=lambda x:x[0],reverse=True)[:TOP_MATCHES]];owner=telegram_subscribers._owner_chat_id()
 if not owner:return 0
 with _LOCK:
  if not _PRIMED:_BASELINE.update(_mid(s) for s in top);_PRIMED=True;log.info("MARKET_TOTAL_ALERT_BASELINE top=%d",len(top));return 0
 sent=0
 for s in top:
  k=_mid(s)
  with _LOCK:
   if k in _BASELINE or k in _ALERTED:continue
   _ALERTED.add(k)
  ok=telegram_subscribers._post_message(owner,_message(s))
  if ok:sent+=1;log.info("MARKET_TOTAL_TOP5_SENT match=%s market=%s delta=%+.2f",k,_name(s),float(s.get("delta_pp",0) or 0))
  else:
   with _LOCK:_ALERTED.discard(k)
 return sent
