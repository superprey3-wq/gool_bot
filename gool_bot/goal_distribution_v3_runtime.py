"""Production GOOL V3: one concrete totals bet per FULL_TIME / FIRST_HALF / SECOND_HALF."""
from __future__ import annotations
import json,logging,os,time,requests
from pathlib import Path
from live_engine import fetch_stats,parse_stats,load_state,save_snapshot,StatsSnapshot
from goal_distribution_v3 import evaluate
from goal_total_market_v3 import fetch_period_totals,select_best
from goal_distribution_v3_card import render
from signal_journal import add_signal,all_signals,update_signal
from telegram_subscribers import get_subscribers
import unified_bot
LOG=logging.getLogger("goal_distribution_v3");AUDIT=Path("goal_distribution_v3_audit.jsonl");STATE=Path("goal_distribution_v3_state.json")
MONKEY_CONTEXT=Path(os.getenv("GOOL_MONKEY_LIVE_CONTEXT","/home/container/monkey_live_context.json"));MONKEY_HISTORY=Path(os.getenv("GOOL_MONKEY_LIVE_HISTORY","/home/container/monkey_live_stats_history.json"))
PERIODS={"FULL_TIME":(12,82,94),"FIRST_HALF":(15,40,47),"SECOND_HALF":(52,84,94)}
TREND=("xg","xgot","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")
def _load():
 try:d=json.loads(STATE.read_text("utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _save(d):
 cutoff=time.time()-12*3600;d={k:v for k,v in d.items() if float(v.get("ts",0) or 0)>=cutoff};STATE.write_text(json.dumps(d,ensure_ascii=False),"utf-8")
def _audit(row):
 try:
  with AUDIT.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
 except Exception:LOG.exception("CORE_V3_AUDIT_FAIL")
def _key(period,eid):return f"v3:{period}:{eid}"
def _already(period,eid):return any(str(r.get("dedupe_key"))==_key(period,eid) for r in all_signals())
def _context_events():
 try:
  p=json.loads(MONKEY_CONTEXT.read_text("utf-8"));
  if time.time()-float(p.get("ts",0) or 0)>50:return {}
  return p.get("events",{}) if isinstance(p.get("events"),dict) else {}
 except Exception:return {}
def _norm_prev(current,old,window):
 """Convert a 3-10 minute observed delta to an 8-minute-equivalent delta.

This lets a restarted server become useful after a few minutes without treating
cumulative match totals as recent pressure.  Scaling is bounded so a short noisy
window cannot explode the model.
 """
 if not isinstance(old,dict) or window<=0:return old
 factor=max(.8,min(2.0,8.0/float(window)));out={}
 keys=set(current)|set(old)
 for k in keys:
  try:
   ca,cb=current.get(k,(0,0));oa,ob=old.get(k,(0,0));
   if k in TREND:out[k]=(max(0.,float(ca)-max(0.,float(ca)-float(oa))*factor),max(0.,float(cb)-max(0.,float(cb)-float(ob))*factor))
   else:out[k]=(float(oa),float(ob))
  except Exception:out[k]=old.get(k,current.get(k,(0,0)))
 return out
def _adaptive_previous(eid,minute,current):
 """Prefer ~8m history, but accept a real 3-10m local snapshot after restart."""
 try:rows=load_state().get(str(eid),[]) or []
 except Exception:rows=[]
 candidates=[]
 for r in rows:
  try:
   gap=int(minute)-int(r.get("minute",999));vals=r.get("values",{})
   if 3<=gap<=10 and isinstance(vals,dict):candidates.append((abs(gap-8),-gap,gap,{k:tuple(v) for k,v in vals.items()}))
  except Exception:pass
 if not candidates:return None,0
 _,_,gap,prev=min(candidates,key=lambda x:(x[0],x[1]));return _norm_prev(current,prev,gap),gap
def _warm_previous(eid,minute,current):
 """Optional Monkey history fallback. MAIN never writes it."""
 try:d=json.loads(MONKEY_HISTORY.read_text("utf-8"));rows=d.get(str(eid),[]) if isinstance(d,dict) else []
 except Exception:return None,0
 candidates=[]
 for r in rows:
  try:
   gap=int(minute)-int(r.get("minute",999));vals=r.get("values",{})
   if 3<=gap<=10 and isinstance(vals,dict):candidates.append((abs(gap-8),-gap,gap,{k:tuple(v) for k,v in vals.items()}))
  except Exception:pass
 if not candidates:return None,0
 _,_,gap,prev=min(candidates,key=lambda x:(x[0],x[1]));return _norm_prev(current,prev,gap),gap
def _history(m,s):
 cached=s.get("history")
 if isinstance(cached,dict):return cached
 out={"available":False,"mult":1.0}
 try:
  from match_history import fetch_match_history,analyse_history
  a=analyse_history(fetch_match_history(m.event_id,m.home,m.away,limit=5)) or {};valid=[x for x in (a.get("home",{}),a.get("away",{}),a.get("h2h",{})) if isinstance(x,dict) and x.get("n",0)]
  if valid:
   avg=float(a.get("historical_avg_total",0) or 0);over25=sum(float(x.get("over25",0) or 0) for x in valid)/len(valid);mult=max(.88,min(1.12,1+(avg-2.6)*.04+(over25-.5)*.10));out={"available":True,"avg_total":round(avg,2),"over25":round(over25,3),"samples":sum(int(x.get("n",0) or 0) for x in valid),"mult":round(mult,3)}
 except Exception as exc:LOG.info("CORE_V3_HISTORY_UNAVAILABLE %s %s",m.event_id,exc)
 s["history"]=out;return out
def _send(m,period,dec,bet,result=None):
 token=str(getattr(unified_bot,"BOT_TOKEN","") or "");subs=get_subscribers()
 if not token or not subs:return False
 try:png=render(m,period,dec,bet,result)
 except Exception:LOG.exception("CORE_V3_CARD_FAIL");return False
 pick=("ТБ" if bet.get("side")=="OVER" else "ТМ")+f" {float(bet.get('line')):g}";caption=f"🎯 GOOL • {period} • {pick}"+(f" @ {float(bet['odd']):.2f}" if bet.get("odd") else "") if result is None else f"{'✅' if result=='win' else '↔️' if result=='push' else '❌'} GOOL • {period} • {pick} • {result.upper()}"
 ok=0
 for cid in subs:
  try:r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(cid),"caption":caption},files={"photo":("gool-v3.png",png,"image/png")},timeout=25);ok+=int(r.ok)
  except requests.RequestException:pass
 LOG.info("CORE_V3_DELIVERED event=%s period=%s result=%s ok=%d/%d",m.event_id,period,result or "signal",ok,len(subs));return ok>0
def _record(m,period,dec,bet,hist):
 row={"journal_version":10,"kind":"live_total_v3","engine":"GOAL_DISTRIBUTION_V3","period":period,"event_id":str(m.event_id),"home":m.home,"away":m.away,"league":getattr(m,"league","") or "","minute":int(m.minute),"score_at_signal":f"{m.home_score}:{m.away_score}","period_goals_at_signal":int(dec.current_goals),"side":bet["side"],"line":float(bet["line"]),"odd":float(bet["odd"]),"model_probability":float(bet["model_probability"]),"fair_odd":float(bet["fair_odd"]),"value_edge":float(bet["value_edge"]),"ev":float(bet["ev"]),"potential":dec.potential,"threat":dec.threat,"lambda_remaining":float(bet.get("effective_lambda",dec.lambda_remaining)),"p_goal_10m":dec.p_goal_10m,"p0":dec.p0,"p1":dec.p1,"p2plus":dec.p2plus,"history_context":hist,"market_source":bet.get("source"),"result":"pending","signal_result":"pending","stake_units":1.0};return add_signal(row,_key(period,m.event_id))
def _period_goals(m,row,state):
 total=int(m.home_score)+int(m.away_score);period=row.get("period")
 if period=="SECOND_HALF":
  ht=(state.get(str(m.event_id),{}) or {}).get("ht_total");return None if ht is None else max(0,total-int(ht))
 return total
def _settle(live,state):
 by={str(m.event_id):m for m in live}
 for row in all_signals():
  if row.get("engine")!="GOAL_DISTRIBUTION_V3" or str(row.get("result"))!="pending":continue
  m=by.get(str(row.get("event_id")));
  if not m:continue
  goals=_period_goals(m,row,state)
  if goals is None:continue
  line=float(row.get("line"));side=str(row.get("side"));period=str(row.get("period"));ended=(period=="FIRST_HALF" and (bool(getattr(m,"is_halftime",False)) or int(m.minute)>=46)) or (period in {"FULL_TIME","SECOND_HALF"} and int(m.minute)>=90);result=None
  if side=="OVER" and goals>line:result="win"
  elif side=="UNDER" and goals>line:result="loss"
  elif ended:
   if abs(goals-line)<1e-9:result="push"
   elif side=="OVER":result="win" if goals>line else "loss"
   else:result="win" if goals<line else "loss"
  if result:update_signal(str(row.get("dedupe_key")),result=result,signal_result=result,final_score=f"{m.home_score}:{m.away_score}",period_goals_final=goals,result_minute=int(m.minute))
def _evaluate_one(m,period,current_goals,stats,prev,margin,s,hist,diag):
 diag["period_eval"]+=1;dec=evaluate(period,int(m.minute),current_goals,stats,prev,margin,0,PERIODS[period][2]);rows=fetch_period_totals(str(m.event_id),period);diag["markets_rows"]+=len(rows);bet=select_best(dec,rows,history_mult=float(hist.get("mult",1.0) or 1.0));row={"ts":time.time(),"event_id":str(m.event_id),"home":m.home,"away":m.away,"score":f"{m.home_score}:{m.away_score}",**dec.dict(),"market_count":len(rows),"selected":bet,"history":hist};_audit(row)
 LOG.info("CORE_V3_DECISION event=%s period=%s minute=%s score=%s potential=%.1f threat=%.1f lambda=%.2f markets=%d bet=%s",m.event_id,period,m.minute,row["score"],dec.potential,dec.threat,dec.lambda_remaining,len(rows),bet)
 if not rows:diag["no_market"]+=1
 if not bet:diag["no_bet"]+=1;return 0
 diag["bet_candidates"]+=1
 if _already(period,m.event_id):diag["duplicate"]+=1;return 0
 return 1 if _record(m,period,dec,bet,hist) and _send(m,period,dec,bet) else 0
def scan(live):
 state=_load();ctx=_context_events();now=time.time();sent=0;diag={"discovered":len(live),"context_stats":0,"stats_body":0,"stats_ok":0,"no_stats_body":0,"no_stats_parse":0,"baseline_local":0,"baseline_monkey":0,"baseline_3_10m":0,"no_baseline":0,"period_eval":0,"markets_rows":0,"no_market":0,"no_bet":0,"bet_candidates":0,"duplicate":0};_settle(live,state)
 for m in live:
  minute=int(getattr(m,"minute",0) or 0);eid=str(m.event_id);total=int(m.home_score)+int(m.away_score);margin=int(m.home_score)-int(m.away_score);s=state.setdefault(eid,{"ts":now});s["ts"]=now
  if bool(getattr(m,"is_halftime",False)) or 45<=minute<=47:s.setdefault("ht_total",total)
  ce=ctx.get(eid,{}) if isinstance(ctx,dict) else {};stats={k:tuple(v) for k,v in (ce.get("stats",{}) or {}).items()} if isinstance(ce,dict) and isinstance(ce.get("stats"),dict) else {}
  if stats:diag["context_stats"]+=1
  else:
   body=fetch_stats(eid)
   if not body:diag["no_stats_body"]+=1;LOG.info("CORE_V3_REJECT event=%s minute=%s reason=no_stats_body",eid,minute);continue
   diag["stats_body"]+=1;stats=parse_stats(body)
   if not stats:diag["no_stats_parse"]+=1;LOG.info("CORE_V3_REJECT event=%s minute=%s reason=no_stats_parse",eid,minute);continue
  diag["stats_ok"]+=1;prev,gap=_adaptive_previous(eid,minute,stats)
  if prev is not None:diag["baseline_local"]+=1;diag["baseline_3_10m"]+=1
  else:
   prev,gap=_warm_previous(eid,minute,stats)
   if prev is not None:diag["baseline_monkey"]+=1;diag["baseline_3_10m"]+=1
  hist=_history(m,s)
  if prev is None:diag["no_baseline"]+=1;LOG.info("CORE_V3_WAIT event=%s minute=%s reason=no_3m_baseline",eid,minute)
  else:LOG.info("CORE_V3_BASELINE event=%s minute=%s window=%dm source=%s",eid,minute,gap,"local" if diag["baseline_local"] else "history")
  if prev is not None and PERIODS["FULL_TIME"][0]<=minute<=PERIODS["FULL_TIME"][1] and not bool(getattr(m,"is_halftime",False)):sent+=_evaluate_one(m,"FULL_TIME",total,stats,prev,margin,s,hist,diag)
  if prev is not None and PERIODS["FIRST_HALF"][0]<=minute<=PERIODS["FIRST_HALF"][1] and not bool(getattr(m,"is_halftime",False)):sent+=_evaluate_one(m,"FIRST_HALF",total,stats,prev,margin,s,hist,diag)
  if prev is not None and PERIODS["SECOND_HALF"][0]<=minute<=PERIODS["SECOND_HALF"][1] and "ht_total" in s:sent+=_evaluate_one(m,"SECOND_HALF",max(0,total-int(s["ht_total"])),stats,prev,margin,s,hist,diag)
  save_snapshot(eid,StatsSnapshot(int(time.time()),minute,stats))
 _save(state);LOG.info("CORE_V3_CYCLE matches=%d sent=%d systems=FT+1H+2H",len(live),sent);LOG.info("CORE_V3_POOL_DIAG %s",diag);return sent
LOG.info("CORE V3 PRODUCTION active | adaptive baseline=3-10m normalized-to-8m | FULL_TIME+FIRST_HALF+SECOND_HALF")
