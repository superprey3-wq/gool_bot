"""Owner-only sharp full-match total alerts: LIVE + starts within two hours.

Also stores each delivered alert, enriches it with GOOL/Flashscore LIVE minute+score,
and settles the recommended total after the match disappears from LIVE.
"""
from __future__ import annotations
import json,logging,os,re,threading,time,requests
from pathlib import Path
import market_node_bridge,telegram_subscribers
from prematch_market_lab import fetch_odds,normalize_odds
log=logging.getLogger("market_test_signal")
_LOCK=threading.RLock();_ALERTED=set();_BASELINE=set();_PRIMED=False;TOP_MATCHES=5;WINDOW=7200
_PM_LAST=0.0;_PM_INTERVAL=60;_PM_STATE={};MIN_RECOMMENDED_ODD=1.35
_LIVE_CTX={};_LAST_LIVE_CTX=0.0

def _store_path():
 root=Path(os.getenv("RUNTIME_DATA_DIR","/data" if Path("/data").exists() else "."));root.mkdir(parents=True,exist_ok=True);return root/"market_total_alerts.json"
def _load_store():
 try:
  p=_store_path();d=json.loads(p.read_text("utf-8")) if p.exists() else {};return d if isinstance(d,dict) else {}
 except Exception:return {}
def _save_store(d):
 try:
  p=_store_path();tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(d,ensure_ascii=False,separators=(",",":")),"utf-8");os.replace(tmp,p)
 except Exception as e:log.warning("MARKET_TOTAL_STORE_FAIL %s",e)
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
def _opposite_name(s):
 ln=_num(s.get("last_line"),1).rstrip("0").rstrip(".");return ("ТМ " if _is_over(s) else "ТБ ")+ln
def _sharp(s):
 try:d=abs(float(s.get("delta_pp",0) or 0));sec=int(s.get("elapsed",0) or 0);return d>=8 or (d>=5 and sec<=180)
 except Exception:return False
def _price_ok(s):
 try:return float(s.get("last_odds") or 0)>=MIN_RECOMMENDED_ODD
 except Exception:return False
def _norm(x):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(x or "").lower()).split())
def _ctx_for(s):
 fid=str(s.get("fs_id") or s.get("event_id") or "")
 with _LOCK:
  if fid and fid in _LIVE_CTX:return dict(_LIVE_CTX[fid])
  h,a=_norm(s.get("home")),_norm(s.get("away"))
  for c in _LIVE_CTX.values():
   if _norm(c.get("home"))==h and _norm(c.get("away"))==a:return dict(c)
 return {}
def _enrich(s):
 x=dict(s);c=_ctx_for(s)
 if c:
  x.setdefault("fs_id",c.get("event_id"));x["minute"]=c.get("minute");x["score_at_alert"]=f"{c.get('home_score',0)}:{c.get('away_score',0)}";x["league"]=c.get("league") or x.get("league")
 return x
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
def _recommendation(s,d):
 if d>0:return f"🎯 <b>Рекомендованная ставка:</b> <b>{_name(s)}</b> · текущий кэф {_num(s.get('last_odds'))}"
 return f"🎯 <b>Рекомендованное направление:</b> <b>{_opposite_name(s)}</b>\n<i>Кэф противоположной стороны не получен — не подставляю выдуманное значение.</i>"
def _message(s):
 s=_enrich(s);d=float(s.get("delta_pp",0) or 0);a=s.get("start_odds");b=s.get("last_odds");p0=_prob(a);p1=_prob(b);sec=max(1,int(s.get("elapsed",0) or 0));arrow="↓" if d>0 else "↑" if d<0 else "→"
 head=f"⏱ {_time_label(s)}"+(f" · счёт <b>{s.get('score_at_alert')}</b>" if s.get("score_at_alert") else "")
 parts=["🚨 <b>ТОП-ПРОГРУЗ ТОТАЛА</b>",f"⚽ <b>{s.get('home') or '?'} — {s.get('away') or '?'}</b>",head]
 if s.get("league"):parts.append(f"🏆 {s.get('league')}")
 parts.extend([f"📊 <b>{_name(s)}</b>","","<b>БЫЛО → СТАЛО</b>",f"Кэф: <b>{_num(a)} → {_num(b)} {arrow}</b>"])
 if p0 is not None and p1 is not None:parts.append(f"Вероятность: <b>{p0:.0f}% → {p1:.0f}%</b>")
 parts.append(f"Изменение: <b>{d:+.2f} п.п.</b> за <b>{sec} сек</b>")
 parts.append(f"🔒 Блокировок рынка: <b>{int(s.get('suspends',0) or 0)}</b> · reopen: <b>{int(s.get('reopens',0) or 0)}</b>")
 parts.extend(["",_meaning(s,d),"",_recommendation(s,d),"<i>Только тоталы матча ТБ/ТМ · кэф от 1.35 · LIVE или старт ≤2ч · топ-5 · один сигнал на матч.</i>"]);return "\n".join(parts)
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
   out.append({"key":"pm:"+eid,"market_key":key,"home":f.get("home"),"away":f.get("away"),"event_id":eid,"fs_id":eid,"league":f.get("league"),"market":f"TOTAL {sel}","selection":sel,"last_line":float(line),"start_odds":prev[1],"last_odds":odd,"delta_pp":round(delta,2),"elapsed":elapsed,"start_ts":float(f.get("start_ts") or 0),"status":"prematch","suspends":0,"reopens":0})
 log.info("MARKET_PREMATCH_SCAN fixtures=%d movements=%d",len(near),len(out));return out
def _mid(s):return str(s.get("fs_id") or s.get("key") or f"{s.get('home')}|{s.get('away')}")
def _recommended_side(s):
 d=float(s.get("delta_pp",0) or 0);over=_is_over(s);return "over" if (over and d>0) or ((not over) and d<0) else "under"
def _record_alert(s):
 x=_enrich(s);rid=_mid(x);d=_load_store();rows=d.setdefault("alerts",{});now=int(time.time())
 rows[rid]={"id":rid,"event_id":str(x.get("fs_id") or x.get("event_id") or ""),"home":x.get("home"),"away":x.get("away"),"league":x.get("league"),"created_ts":now,"minute":x.get("minute"),"score_at_alert":x.get("score_at_alert"),"line":x.get("last_line"),"side":_recommended_side(x),"shown_market":_name(x),"recommended_market":_name(x) if float(x.get("delta_pp",0) or 0)>0 else _opposite_name(x),"odd":x.get("last_odds") if float(x.get("delta_pp",0) or 0)>0 else None,"delta_pp":x.get("delta_pp"),"suspends":int(x.get("suspends",0) or 0),"reopens":int(x.get("reopens",0) or 0),"status":"tracking","last_seen_ts":now,"last_score":x.get("score_at_alert")}
 _save_store(d)
def _settle(side,line,score):
 try:h,a=map(int,str(score).split(":",1));total=h+a;ln=float(line)
 except Exception:return "unknown"
 if total==ln:return "push"
 return "win" if (side=="over" and total>ln) or (side=="under" and total<ln) else "loss"
def update_live_context(live):
 global _LAST_LIVE_CTX
 now=time.time();ctx={}
 for m in live or []:
  eid=str(getattr(m,"event_id","") or "")
  if not eid:continue
  ctx[eid]={"event_id":eid,"home":getattr(m,"home",""),"away":getattr(m,"away",""),"league":getattr(m,"league","") or getattr(m,"tournament",""),"minute":getattr(m,"minute",0),"home_score":int(getattr(m,"home_score",0) or 0),"away_score":int(getattr(m,"away_score",0) or 0)}
 with _LOCK:_LIVE_CTX.clear();_LIVE_CTX.update(ctx);_LAST_LIVE_CTX=now
 d=_load_store();changed=False
 for r in (d.get("alerts") or {}).values():
  if not isinstance(r,dict) or r.get("status")!="tracking":continue
  eid=str(r.get("event_id") or "");c=ctx.get(eid)
  if c:
   r["last_seen_ts"]=int(now);r["last_score"]=f"{c['home_score']}:{c['away_score']}";changed=True;continue
  last=float(r.get("last_seen_ts",0) or 0)
  if last and now-last>=600 and r.get("last_score"):
   res=_settle(r.get("side"),r.get("line"),r.get("last_score"));r.update({"status":"settled" if res!="unknown" else "unknown","result":res,"final_score":r.get("last_score"),"settled_ts":int(now)});changed=True
 if changed:_save_store(d)
def build_results_text():
 d=_load_store();rows=[x for x in (d.get("alerts") or {}).values() if isinstance(x,dict)];rows.sort(key=lambda x:int(x.get("created_ts",0) or 0));settled=[r for r in rows if r.get("result") in ("win","loss","push")];w=sum(r.get("result")=="win" for r in settled);l=sum(r.get("result")=="loss" for r in settled);p=sum(r.get("result")=="push" for r in settled);dec=w+l;acc=round(100*w/dec,1) if dec else 0
 lines=["📊 <b>ИТОГИ ПРОГРУЗОВ</b>",f"Закрыто: <b>{len(settled)}</b> · ✅ {w} · ❌ {l} · ↩️ {p}"+(f" · точность <b>{acc}%</b>" if dec else ""),""]
 for r in settled[-10:][::-1]:
  mark="✅" if r.get("result")=="win" else "❌" if r.get("result")=="loss" else "↩️";od=f" @ {float(r['odd']):.2f}" if r.get("odd") else "";entry=(f" · {r.get('minute')}' · {r.get('score_at_alert')}" if r.get("minute") else "")
  lines.append(f"{mark} <b>{r.get('home')} — {r.get('away')}</b>{entry}\n   🎯 {r.get('recommended_market')}{od} · итог <b>{r.get('final_score') or '—'}</b> · 🔒 {r.get('suspends',0)}")
 tracking=sum(r.get("status")=="tracking" for r in rows)
 if tracking:lines.extend(["",f"⏳ Сейчас отслеживается: <b>{tracking}</b>"])
 if not rows:lines.append("Пока сохранённых автопрогрузов нет.")
 return "\n".join(lines)
def scan_once():
 global _PRIMED
 live=_fetch_live();prematch=_pm_rows();raw=live+prematch;totals=[s for s in raw if _total(s)];priced=[s for s in totals if _price_ok(s)];sharp=[s for s in priced if _sharp(s)];signals=[s for s in sharp if _eligible_time(s)]
 log.info("MARKET_TOTAL_FILTER live=%d prematch=%d totals=%d priced=%d sharp=%d eligible=%d",len(live),len(prematch),len(totals),len(priced),len(sharp),len(signals))
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
  if ok:_record_alert(s);sent+=1;log.info("MARKET_TOTAL_TOP5_SENT match=%s market=%s delta=%+.2f",k,_name(s),float(s.get("delta_pp",0) or 0))
  else:
   with _LOCK:_ALERTED.discard(k)
 return sent
