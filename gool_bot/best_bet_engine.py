"""Unified GOOL BEST BET engine.

Ranks every verified actionable FULL_TIME market already produced by GOOL and
publishes at most one active recommendation per match. Existing CORE/1H/2H
engines remain evidence providers; this module is the final market arbiter.
"""
from __future__ import annotations
import logging,os,time
import live_candidate_patch as lc
import telegram_subscribers
from signal_journal import add_signal

log=logging.getLogger("best_bet_engine")
MIN_SCORE=float(os.getenv("BEST_BET_MIN_SCORE","82"))
MIN_EDGE=float(os.getenv("BEST_BET_MIN_EDGE_PP","4"))
MIN_ODD=float(os.getenv("BEST_BET_MIN_ODD","1.25"))
MAX_ODD=float(os.getenv("BEST_BET_MAX_ODD","4.50"))
COOLDOWN=int(os.getenv("BEST_BET_COOLDOWN_MINUTES","12"))*60
_ACTIVE={}


def _f(v,d=0.):
 try:return float(v)
 except Exception:return d

def _market_name(r):
 kind=str(r.get("market_type") or r.get("extra_market") or "TOTAL").upper();sel=str(r.get("selection") or "").upper();line=r.get("line");team=r.get("team_name") or ""
 if kind in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER"}:return f"ТБ {float(line):g}" if line is not None else "ТБ"
 if kind in {"TOTAL_UNDER","UNDER"}:return f"ТМ {float(line):g}" if line is not None else "ТМ"
 if kind=="BTTS":return "Обе забьют — ДА" if sel not in {"NO","N"} else "Обе забьют — НЕТ"
 if kind=="TEAM_TOTAL_HOME" or kind=="TEAM_TOTAL_AWAY":return f"ИТ {team} Б {float(line):g}" if line is not None else f"ИТ {team} Б"
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
 parts=["🏆 <b>GOOL BEST BET</b>",f"⚽ <b>{m.home} — {m.away}</b>",f"⏱ LIVE · {minute}' · счёт <b>{score}</b>","",f"🎯 <b>{best['name']} @ {best['odd']:.2f}</b>",f"🧠 MODEL: <b>{best['confidence']:.0f}/100</b>",f"📈 MARKET: <b>{best['market_score']:.0f}/100</b> · {best['status']}",f"💎 VALUE EDGE: <b>{best['edge']:+.1f} п.п.</b>",f"🧩 CONTEXT: <b>{best['context']:.0f}/100</b>",f"⭐ MASTER: <b>{best['score']:.0f}/100</b>"]
 if alts:parts.extend(["",f"🥈 Ближайший кандидат: {alts[0]['name']} @ {alts[0]['odd']:.2f} · {alts[0]['score']:.0f}/100"])
 parts.extend(["","<i>Одна лучшая ставка на матч · рынок + модель + value + контекст. При слабом/конфликтном преимуществе — NO BET.</i>"])
 return "\n".join(parts)

def _record(m,best,alts):
 eid=str(getattr(m,"event_id","") or "");minute=int(getattr(m,"minute",0) or 0);score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";r=best["row"]
 key=f"best_bet:{eid}:{minute}:{best['name']}";record={"kind":"best_bet","reason":"best_bet","event_id":eid,"home":m.home,"away":m.away,"minute":minute,"score_at_signal":score,"master":best["score"],"model_score":best["confidence"],"market_score":best["market_score"],"context_score":best["context"],"value_edge_pp":best["edge"],"market_status":best["status"],"primary":{"market_type":r.get("market_type"),"market":r.get("market") or r.get("extra_market"),"selection":r.get("selection"),"line":r.get("line"),"team_side":r.get("team_side"),"team_name":r.get("team_name"),"odd":best["odd"],"label":best["name"]},"alternatives":[{"label":x["name"],"odd":x["odd"],"master":x["score"],"edge":x["edge"]} for x in alts[:3]],"stake_units":1.0,"result":"pending","journal_version":8}
 return add_signal(record,key)

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
 if not _record(m,best,alts):return False
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
