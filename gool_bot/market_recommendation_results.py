"""Track owner market-movement recommendations and settle them after LIVE ends."""
from __future__ import annotations
import time
from math import floor
from signal_journal import all_signals, update_signal
import market_node_bridge as bridge

PENDING={"","pending","wait","waiting"}

def _score(v):
 try:a,b=str(v or "0:0").split(":",1);return int(a),int(b)
 except Exception:return 0,0

def _legs(line):
 line=round(float(line),2);w=floor(line);f=round(line-w,2)
 if f==.25:return [float(w),w+.5]
 if f==.75:return [w+.5,float(w+1)]
 return [line]

def _result_cmp(values, mode):
 rs=[]
 for v in values:
  if mode=="over":rs.append(1 if v>0 else 0 if abs(v)<1e-9 else -1)
  else:rs.append(1 if v<0 else 0 if abs(v)<1e-9 else -1)
 if all(x==1 for x in rs):return "win"
 if all(x==-1 for x in rs):return "loss"
 if all(x==0 for x in rs):return "push"
 return "half-win" if sum(rs)>0 else "half-loss" if sum(rs)<0 else "push"

def settle(rec, score):
 if not isinstance(rec,dict):return "pending"
 h,a=_score(score);ti=rec.get("type_id");gi=rec.get("group_id");line=rec.get("line")
 try:ti=int(ti) if ti is not None else None
 except Exception:ti=None
 try:gi=int(gi) if gi is not None else None
 except Exception:gi=None
 if gi==1 and ti==1:return "win" if h>a else "loss"
 if gi==1 and ti==3:return "win" if a>h else "loss"
 try:ln=float(line)
 except Exception:return "unknown"
 if ti in (9,10):total=h+a;vals=[total-x for x in _legs(ln)];return _result_cmp(vals,"over" if ti==9 else "under")
 if ti in (11,12):vals=[h-x for x in _legs(ln)];return _result_cmp(vals,"over" if ti==12 else "under")
 if ti in (13,14):vals=[a-x for x in _legs(ln)];return _result_cmp(vals,"over" if ti==14 else "under")
 if ti==7:vals=[h+ln-a];return _result_cmp(vals,"over")
 if ti==8:vals=[a+ln-h];return _result_cmp(vals,"over")
 return "unknown"

def _active_rows():
 now=time.time();out=[]
 for r in all_signals():
  if r.get("kind")!="live":continue
  if str(r.get("reason") or "signal") not in {"signal","reentry"}:continue
  if now-float(r.get("created_ts",0) or 0)>8*3600:continue
  if str(r.get("signal_result") or r.get("result") or "pending").lower() not in PENDING:continue
  out.append(r)
 return out

def _pick(diag):
 candidates=[]
 for m in list(diag.get("top_markets") or [])[:5]:
  try:d=float(m.get("delta_pp",0) or 0)
  except Exception:continue
  if abs(d)<1.5:continue
  line=m.get("last_line")
  ti=m.get("type_id");gi=m.get("group_id")
  if ti in (7,8,9,10,11,12,13,14) and line is None:continue
  candidates.append((abs(d),m))
 if not candidates:return None
 m=max(candidates,key=lambda x:x[0])[1]
 return {"market":m.get("market") or "","type_id":m.get("type_id"),"group_id":m.get("group_id"),"line":m.get("last_line"),"odd":m.get("last_odds"),"delta_pp":m.get("delta_pp"),"dot":m.get("dot"),"captured_ts":int(time.time())}

def capture_active():
 saved=0
 for r in _active_rows():
  if r.get("market_recommendation"):continue
  try:diag=bridge.diagnostic_for_match(r.get("home"),r.get("away"))
  except Exception:continue
  if str(diag.get("match_mode") or "none")=="none":continue
  rec=_pick(diag)
  if not rec:continue
  key=str(r.get("dedupe_key") or "")
  if key and update_signal(key,market_recommendation=rec,market_rec_status="tracking"):
   saved+=1
 return saved

def update_from_live(live):
 now=time.time();current={}
 for m in live or []:
  eid=str(getattr(m,"event_id","") or "")
  if not eid:continue
  current[eid]=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}"
 for r in all_signals():
  rec=r.get("market_recommendation")
  if not rec or r.get("market_rec_status") in {"settled","unknown"}:continue
  eid=str(r.get("event_id") or "");key=str(r.get("dedupe_key") or "")
  if not key or not eid:continue
  if eid in current:
   update_signal(key,market_last_score=current[eid],market_last_seen_ts=int(now),market_rec_status="tracking")
   continue
  last=float(r.get("market_last_seen_ts",0) or 0)
  # Do not call a temporary feed gap full-time. Require 10 minutes missing.
  if last and now-last>=600:
   final=r.get("market_last_score")
   res=settle(rec,final) if final else "unknown"
   update_signal(key,market_rec_status="settled" if res!="unknown" else "unknown",market_rec_result=res,market_rec_final_score=final,market_rec_settled_ts=int(now))

def _rec_name(rec):
 try:ti=int(rec.get("type_id"))
 except Exception:ti=None
 try:gi=int(rec.get("group_id"))
 except Exception:gi=None
 ln=rec.get("line")
 if gi==1 and ti==1:return "П1"
 if gi==1 and ti==3:return "П2"
 if ti==9:return f"ТБ {ln:g}" if isinstance(ln,(int,float)) else f"ТБ {ln}"
 if ti==10:return f"ТМ {ln:g}" if isinstance(ln,(int,float)) else f"ТМ {ln}"
 if ti==11:return f"ИТ1М {ln}"
 if ti==12:return f"ИТ1Б {ln}"
 if ti==13:return f"ИТ2М {ln}"
 if ti==14:return f"ИТ2Б {ln}"
 if ti==7:return f"Ф1 {ln:+g}" if isinstance(ln,(int,float)) else f"Ф1 {ln}"
 if ti==8:return f"Ф2 {ln:+g}" if isinstance(ln,(int,float)) else f"Ф2 {ln}"
 return str(rec.get("market") or "рынок")

def build_results_text():
 rows=[r for r in all_signals() if isinstance(r.get("market_recommendation"),dict)][-80:]
 settled=[r for r in rows if r.get("market_rec_result") in {"win","loss","push","half-win","half-loss"}]
 wins=sum(r.get("market_rec_result") in {"win","half-win"} for r in settled);losses=sum(r.get("market_rec_result") in {"loss","half-loss"} for r in settled);push=sum(r.get("market_rec_result")=="push" for r in settled)
 decisive=wins+losses;hit=round(100*wins/decisive) if decisive else 0
 lines=["📋 <b>ИТОГИ РЫНКА</b>","<i>Проверка рекомендованных ставок из «Линия LIVE» после завершения матчей.</i>",""]
 lines.append(f"Закрыто: <b>{len(settled)}</b> · ✅ {wins} · ❌ {losses} · ↔️ {push}"+(f" · точность <b>{hit}%</b>" if decisive else ""))
 lines.append("")
 for r in settled[-10:][::-1]:
  res=r.get("market_rec_result");mark="✅" if res in {"win","half-win"} else "❌" if res in {"loss","half-loss"} else "↔️"
  rec=r["market_recommendation"];odd=rec.get("odd");odd_txt=f" · кэф {float(odd):.2f}" if odd else ""
  lines.append(f"{mark} <b>{r.get('home')} — {r.get('away')}</b> · {_rec_name(rec)}{odd_txt} · итог {r.get('market_rec_final_score') or '—'}")
 if not settled:lines.append("Пока нет завершённых рекомендаций. Новые рекомендации уже начинают отслеживаться автоматически.")
 tracking=sum(r.get("market_rec_status")=="tracking" for r in rows)
 if tracking:lines.extend(["",f"⏳ Сейчас отслеживается: <b>{tracking}</b>"])
 return "\n".join(lines)
