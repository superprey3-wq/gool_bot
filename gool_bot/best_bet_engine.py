"""Unified GOOL BEST BET engine with entry/result lifecycle.

Ranks verified actionable FULL_TIME markets, publishes at most one active
recommendation per match, journals the exact bet and later sends WIN/LOSS/PUSH
for that same bet after the match is finished/disappears from LIVE.
"""
from __future__ import annotations
import logging,os,time
import live_candidate_patch as lc
import telegram_subscribers
from signal_journal import add_signal,all_signals,update_signal

log=logging.getLogger("best_bet_engine")
MIN_SCORE=float(os.getenv("BEST_BET_MIN_SCORE","82"))
MIN_EDGE=float(os.getenv("BEST_BET_MIN_EDGE_PP","4"))
MIN_ODD=float(os.getenv("BEST_BET_MIN_ODD","1.25"))
MAX_ODD=float(os.getenv("BEST_BET_MAX_ODD","4.50"))
COOLDOWN=int(os.getenv("BEST_BET_COOLDOWN_MINUTES","12"))*60
SETTLE_AFTER=int(os.getenv("BEST_BET_SETTLE_AFTER_SECONDS","600"))
_ACTIVE={}


def _f(v,d=0.):
 try:return float(v)
 except Exception:return d

def _market_name(r):
 kind=str(r.get("market_type") or r.get("extra_market") or "TOTAL").upper();sel=str(r.get("selection") or "").upper();line=r.get("line");team=r.get("team_name") or ""
 if kind in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER"}:return f"ТБ {float(line):g}" if line is not None else "ТБ"
 if kind in {"TOTAL_UNDER","UNDER"}:return f"ТМ {float(line):g}" if line is not None else "ТМ"
 if kind=="BTTS":return "Обе забьют — ДА" if sel not in {"NO","N"} else "Обе забьют — НЕТ"
 if kind in {"TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"}:
  under=sel in {"UNDER","U","NO"} or "UNDER" in str(r.get("market") or "").upper()
  return f"ИТ {team} {'М' if under else 'Б'} {float(line):g}" if line is not None else f"ИТ {team}"
 labels={"HOME":"П1","AWAY":"П2","DRAW":"Х","1X":"1X","X2":"X2","12":"12","DNB_HOME":"П1 (0)","DNB_AWAY":"П2 (0)"}
 return labels.get(sel) or labels.get(kind) or str(r.get("market") or r.get("extra_market") or kind)

def _rank(r,m,p):
 odd=_f(r.get("odd"));
 if odd<MIN_ODD or odd>MAX_ODD:return None
 conf=_f(r.get("selector_confidence"),_f(r.get("confidence"),_f(getattr(p,"score",0))))
 implied=100/odd;edge=_f(r.get("selector_edge"),conf-implied);market=_f(r.get("selector_movement"),_f(r.get("movement_score")))
 status=str(r.get("external_market_status") or r.get("market_status") or r.get("market_consensus") or "").upper()
 confirm={"STEAM":8,"CONFIRMED":6,"PRIMARY_ONLY":-2,"SINGLE_SOURCE":-3,"DISAGREE":-12,"CONFLICT":-18}.get(status,0)
 sources=int(r.get("source_count") or r.get("bookmakers") or 1);context=min(100.,max(0.,_f(getattr(p,"score",0))*.65+_f(getattr(p,"momentum",0))*.35))
 score=conf*.52+max(-15,min(20,edge))*.72+min(8,max(0,sources-1)*2)+market*.35+confirm+context*.12
 if edge<MIN_EDGE:score-=8
 return {"score":round(max(0,min(100,score)),1),"confidence":round(conf,1),"implied":round(implied,1),"edge":round(edge,1),"market_score":round(market,1),"context":round(context,1),"status":status or "PRIMARY","odd":odd,"name":_market_name(r),"row":r}

def _card(m,best,alts):
 score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";minute=int(getattr(m,"minute",0) or 0)
 parts=["🏆 <b>GOOL BEST BET</b>",f"⚽ <b>{m.home} — {m.away}</b>",f"⏱ LIVE · {minute}' · счёт <b>{score}</b>","",f"🎯 <b>СТАВКА: {best['name']} @ {best['odd']:.2f}</b>","✅ <b>ВХОД: ДА</b>",f"🧠 MODEL: <b>{best['confidence']:.0f}/100</b>",f"📈 MARKET: <b>{best['market_score']:.0f}/100</b> · {best['status']}",f"💎 VALUE EDGE: <b>{best['edge']:+.1f} п.п.</b>",f"🧩 CONTEXT: <b>{best['context']:.0f}/100</b>",f"⭐ MASTER: <b>{best['score']:.0f}/100</b>"]
 if alts:parts.extend(["",f"🥈 Ближайший кандидат: {alts[0]['name']} @ {alts[0]['odd']:.2f} · {alts[0]['score']:.0f}/100"])
 parts.extend(["","📒 <b>Ставка записана в журнал и будет рассчитана по финальному счёту.</b>","<i>Одна лучшая ставка на матч · рынок + модель + value + контекст. При слабом/конфликтном преимуществе — NO BET.</i>"])
 return "\n".join(parts)

def _record(m,best,alts):
 eid=str(getattr(m,"event_id","") or "");minute=int(getattr(m,"minute",0) or 0);score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";r=best["row"]
 key=f"best_bet:{eid}:{minute}:{best['name']}";record={"kind":"best_bet","reason":"best_bet","event_id":eid,"home":m.home,"away":m.away,"minute":minute,"score_at_signal":score,"last_score":score,"last_seen_ts":int(time.time()),"master":best["score"],"model_score":best["confidence"],"market_score":best["market_score"],"context_score":best["context"],"value_edge_pp":best["edge"],"market_status":best["status"],"primary":{"market_type":r.get("market_type"),"market":r.get("market") or r.get("extra_market"),"selection":r.get("selection"),"line":r.get("line"),"team_side":r.get("team_side"),"team_name":r.get("team_name"),"odd":best["odd"],"label":best["name"]},"alternatives":[{"label":x["name"],"odd":x["odd"],"master":x["score"],"edge":x["edge"]} for x in alts[:3]],"stake_units":1.0,"bet_result":"pending","result":"pending","result_card_sent":False,"journal_version":8}
 return key if add_signal(record,key) else None

def _parse_score(score):
 try:a,b=str(score).split(":",1);return int(a),int(b)
 except Exception:return None

def _ou_result(total,line,side):
 line=float(line);side=str(side).upper()
 if abs(total-line)<1e-9:return "push"
 return "win" if (side=="OVER" and total>line) or (side=="UNDER" and total<line) else "loss"

def _settle(primary,score):
 sc=_parse_score(score)
 if not sc or not isinstance(primary,dict):return None
 h,a=sc;kind=str(primary.get("market_type") or primary.get("market") or "").upper();sel=str(primary.get("selection") or "").upper();line=primary.get("line")
 if kind in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER","TOTAL_UNDER","UNDER"}:
  if line is None:return None
  side="UNDER" if kind in {"TOTAL_UNDER","UNDER"} or sel in {"UNDER","U"} else "OVER"
  return _ou_result(h+a,line,side)
 if kind=="BTTS":
  yes=sel not in {"NO","N"};hit=h>0 and a>0;return "win" if hit==yes else "loss"
 if kind in {"TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"}:
  if line is None:return None
  goals=h if kind.endswith("HOME") else a;side="UNDER" if sel in {"UNDER","U"} or "UNDER" in str(primary.get("market") or "").upper() else "OVER";return _ou_result(goals,line,side)
 if sel in {"HOME","1","П1"}:return "win" if h>a else "loss"
 if sel in {"AWAY","2","П2"}:return "win" if a>h else "loss"
 if sel in {"DRAW","X","Х"}:return "win" if h==a else "loss"
 if sel=="1X":return "win" if h>=a else "loss"
 if sel=="X2":return "win" if a>=h else "loss"
 if sel=="12":return "win" if h!=a else "loss"
 if sel in {"DNB_HOME","HOME_DNB"}:return "win" if h>a else "push" if h==a else "loss"
 if sel in {"DNB_AWAY","AWAY_DNB"}:return "win" if a>h else "push" if h==a else "loss"
 return None

def _pnl(result,odd):
 if result=="win":return round(float(odd)-1,3)
 if result=="loss":return -1.0
 if result=="push":return 0.0
 return None

def _result_card(row,result,score,pnl):
 icon={"win":"✅","loss":"❌","push":"↩️"}.get(result,"⚪");title={"win":"СТАВКА ЗАШЛА","loss":"СТАВКА НЕ ЗАШЛА","push":"ВОЗВРАТ"}.get(result,"РЕЗУЛЬТАТ");p=row.get("primary") or {};odd=_f(p.get("odd"));label=p.get("label") or p.get("market") or "ставка"
 return "\n".join([f"{icon} <b>GOOL BEST BET · {title}</b>",f"⚽ <b>{row.get('home')} — {row.get('away')}</b>",f"🏁 Финальный счёт: <b>{score}</b>","",f"🎯 Ставка: <b>{label} @ {odd:.2f}</b>",f"📍 Вход: {row.get('minute')}' · {row.get('score_at_signal')}",f"⭐ MASTER на входе: <b>{_f(row.get('master')):.0f}/100</b>",f"💰 PnL: <b>{pnl:+.2f} ед.</b>","",f"📒 <b>Журнал: {title}</b>"])

def update_results(live):
 now=int(time.time());by={str(getattr(m,"event_id","") or ""):m for m in (live or [])};sent=0
 for row in all_signals():
  if row.get("kind")!="best_bet" or str(row.get("result") or "pending").lower() not in {"","pending","wait","waiting"}:continue
  key=str(row.get("dedupe_key") or "");eid=str(row.get("event_id") or "");m=by.get(eid)
  if m is not None:
   score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";update_signal(key,last_score=score,last_seen_ts=now);continue
  last=int(row.get("last_seen_ts",0) or 0)
  if not last or now-last<SETTLE_AFTER:continue
  score=row.get("last_score")
  result=_settle(row.get("primary"),score)
  if not result:continue
  odd=_f((row.get("primary") or {}).get("odd"));pnl=_pnl(result,odd)
  update_signal(key,result=result,bet_result=result,bet_pnl_units=pnl,final_score=score,settled_ts=now,result_source="best_bet_final_score",result_card_sent=True)
  text=_result_card(row,result,score,pnl)
  for chat in telegram_subscribers.get_subscribers():telegram_subscribers._post_message(chat,text)
  sent+=1;log.info("BEST_BET_SETTLED %s result=%s score=%s pnl=%s",eid,result,score,pnl)
 return sent

def evaluate_match(m):
 eid=str(getattr(m,"event_id","") or "");now=time.time();prev=_ACTIVE.get(eid)
 if prev and now-prev<COOLDOWN:return False
 try:
  entries=lc._fetch_entries(m);s=lc._stats(m);p=lc.calculate_goal_pressure(s,getattr(m,"minute",0))
 except Exception:return False
 try:recs,market=lc._market(entries,m,p)
 except Exception as e:log.info("BEST_BET market unavailable %s %s",eid,e);return False
 ranked=[]
 for r in recs or []:
  if r.get("scope")!="FULL_TIME" or r.get("odd") is None:continue
  x=_rank(r,m,p)
  if x:ranked.append(x)
 ranked.sort(key=lambda x:x["score"],reverse=True)
 if not ranked:return False
 best=ranked[0];alts=ranked[1:4]
 if best["score"]<MIN_SCORE or best["edge"]<MIN_EDGE or best["status"] in {"CONFLICT","DISAGREE"}:return False
 key=_record(m,best,alts)
 if not key:return False
 sent=False
 for chat in telegram_subscribers.get_subscribers():sent=telegram_subscribers._post_message(chat,_card(m,best,alts)) or sent
 if sent:_ACTIVE[eid]=now;log.info("BEST_BET_SENT %s %s score=%.1f edge=%.1f",eid,best["name"],best["score"],best["edge"])
 return sent

def scan(live):
 sent=0
 for m in live or []:
  try:sent+=1 if evaluate_match(m) else 0
  except Exception:log.exception("BEST_BET failed event=%s",getattr(m,"event_id",""))
 return sent
