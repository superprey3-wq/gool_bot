"""Full multi-strategy LIVE evaluation engine.

Every discovered match is scored through all applicable routes.  The scores are
transparent heuristics (0-100), not guaranteed probabilities.  They are logged
and persisted so they can later be calibrated/backtested against real outcomes.
"""
from __future__ import annotations
import logging, math, time
import unified_bot
from live_engine import StatsSnapshot, calculate_goal_pressure, fetch_stats, fetch_summary, get_previous_values, parse_goal_timeline, parse_stats, save_snapshot
from match_history import analyse_history, fetch_match_history

logger=logging.getLogger("live_candidate_patch")
_HISTORY_CACHE={}; _HISTORY_CACHE_SECONDS=15*60

def _pair(stats,key):
    a,b=stats.get(key,(0.,0.)); return float(a),float(b)
def _total(stats,key): return sum(_pair(stats,key))
def _clamp(v): return round(max(0.,min(100.,v)),1)

def _history(match):
    now=time.time(); c=_HISTORY_CACHE.get(match.event_id)
    if c and now-c[0]<_HISTORY_CACHE_SECONDS:return c[1],c[2]
    try: a=analyse_history(fetch_match_history(match.event_id,match.home,match.away,limit=5))
    except Exception as e:
        logger.info("HISTORY %s unavailable: %s",match.event_id,e); return 0.,{}
    valid=[x for x in (a.get("home",{}),a.get("away",{}),a.get("h2h",{})) if x.get("n",0)]
    if not valid:s=0.
    else:
        avg=float(a.get("historical_avg_total",0) or 0); o25=sum(float(x.get("over25",0) or 0) for x in valid)/len(valid); o35=sum(float(x.get("over35",0) or 0) for x in valid)/len(valid); o45=sum(float(x.get("over45",0) or 0) for x in valid)/len(valid)
        s=_clamp(min(45,avg/4*45)+25*o25+18*o35+12*o45)
    _HISTORY_CACHE[match.event_id]=(now,s,a); return s,a

def _domination(m,s):
    minute=max(1,m.minute); pace=min(1.45,45/minute) if minute<=45 else min(1.25,90/minute)
    return _clamp(min(25,_total(s,"shots")*pace/10*25)+min(25,_total(s,"shots_on_target")*pace/5*25)+min(18,_total(s,"xg")*pace/1.2*18)+min(12,(m.home_score+m.away_score)/2*12)+min(8,_total(s,"corners")*pace/5*8)+min(7,_total(s,"big_chances")*pace/2*7)+min(5,(_total(s,"shots_inside_box")*.22+_total(s,"touches_box")*.08)*pace))

def _threat(s):
    return _clamp(_total(s,"shots_inside_box")*4+_total(s,"touches_box")*1.2+_total(s,"corners")*4+_total(s,"big_chances")*13+_total(s,"shots_on_target")*5)
def _xg_under(m,s):
    xg=_total(s,"xg"); goals=m.home_score+m.away_score
    # Strong when chance quality materially exceeds actual conversion; still useful at 0:0.
    return _clamp(max(0,xg-goals)*42+xg*12+_total(s,"shots_on_target")*2)
def _fast_start(m,s,dom,hist):
    if m.minute>45 or m.is_halftime:return 0.
    pace=min(1.6,45/max(10,m.minute)); return _clamp(dom*.45+hist*.15+min(100,_total(s,"shots")*pace*5)*.2+min(100,_total(s,"shots_on_target")*pace*10)*.2)
def _second_half(m,s,dom,hist,under):
    if m.minute<45:return 0.
    # HT underperformance and strong accumulated creation raise second-half explosion score.
    return _clamp(dom*.30+hist*.25+under*.25+min(100,_total(s,"shots_on_target")*10+_total(s,"corners")*4)*.20)
def _chase(m,s):
    if m.minute<55:return 0.
    hs,as_=m.home_score,m.away_score
    if hs==as_:return 20.
    trailing=0 if hs<as_ else 1; deficit=abs(hs-as_); shots=_pair(s,"shots")[trailing]; sot=_pair(s,"shots_on_target")[trailing]; xg=_pair(s,"xg")[trailing]; corners=_pair(s,"corners")[trailing]; touches=_pair(s,"touches_box")[trailing]
    state=20 if deficit==1 else 30 if deficit>=2 else 0
    return _clamp(state+shots*4+sot*9+xg*18+corners*4+touches*1.1)
def _late(m,dom,momentum,chase,threat,hist):
    if m.minute<62:return 0.
    time_factor=min(100,max(0,(m.minute-60)*4)); return _clamp(dom*.22+momentum*.22+chase*.22+threat*.18+hist*.08+time_factor*.08)
def _post_goal(m,goal_times,momentum,dom):
    if not goal_times:return 0.
    try:last=max(int(str(x).split("'",1)[0]) for x in goal_times)
    except Exception:return 0.
    since=max(0,m.minute-last)
    if since>15:return 0.
    recency=max(0,100-since*6); return _clamp(recency*.45+momentum*.30+dom*.25)
def _side_pressure(m,s,side):
    shots=_pair(s,"shots")[side]; sot=_pair(s,"shots_on_target")[side]; xg=_pair(s,"xg")[side]; big=_pair(s,"big_chances")[side]; inside=_pair(s,"shots_inside_box")[side]; touches=_pair(s,"touches_box")[side]; corners=_pair(s,"corners")[side]
    return _clamp(shots*3+sot*8+xg*20+big*12+inside*2+touches*.8+corners*3)
def _hazards(m,master):
    # Convert a bounded heuristic intensity into transparent near-term estimates.
    # These are stored for calibration and deliberately capped until enough journal data exists.
    rate=(2.7/90)*(0.45+1.35*master/100)
    p5=(1-math.exp(-rate*5))*100; p10=(1-math.exp(-rate*10))*100; p15=(1-math.exp(-rate*15))*100
    remain=(47-m.minute) if m.minute<=45 else (94-m.minute); pend=(1-math.exp(-rate*max(0,remain)))*100
    return tuple(round(min(92,x),1) for x in (p5,p10,p15,pend))

def _evaluate(m,s,p,goal_times):
    hist,_=_history(m); dom=_domination(m,s); threat=_threat(s); under=_xg_under(m,s); fast=_fast_start(m,s,dom,hist); second=_second_half(m,s,dom,hist,under); chase=_chase(m,s); late=_late(m,dom,p.momentum,chase,threat,hist); chaos=_post_goal(m,goal_times,p.momentum,dom); home=_side_pressure(m,s,0); away=_side_pressure(m,s,1)
    strategies={"MOMENTUM":p.score,"DOMINATION":dom,"HISTORY":hist,"FAST_START":fast,"SECOND_HALF":second,"CHASE":chase,"LATE_GOAL":late,"POST_GOAL_CHAOS":chaos,"XG_UNDERPERFORMANCE":under,"THREAT":threat,"HOME_PRESSURE":home,"AWAY_PRESSURE":away}
    applicable={k:v for k,v in strategies.items() if v>0}; ranked=sorted(applicable.items(),key=lambda kv:kv[1],reverse=True); top=ranked[:4]
    # Specialist routes can qualify independently; corroboration lowers the bar slightly.
    strong=[(k,v) for k,v in ranked if k not in ("HOME_PRESSURE","AWAY_PRESSURE") and v>=72]
    corroborated=[v for k,v in ranked if k not in ("HOME_PRESSURE","AWAY_PRESSURE") and v>=64]
    qualifies=bool(strong) or len(corroborated)>=3
    master=_clamp(sum(v*w for (k,v),w in zip(top,(.40,.28,.20,.12))) if top else 0)
    hazards=_hazards(m,master)
    route="+".join(k for k,v in strong[:3]) if strong else ("MULTI_CONFIRM" if qualifies else "REJECT")
    return qualifies,route,master,strategies,hazards

async def scan_live_once_multi():
    live=await unified_bot.discover_live_matches(); logger.info("Найдено LIVE-матчей: %d | FULL STRATEGY PIPELINE",len(live)); state=unified_bot._load_sent(); sent=0; live_ids={m.event_id for m in live}
    for key in list(state):
        if key.startswith("TRACK:") and key.split(":",1)[1] not in live_ids:state.pop(key,None)
    for m in live:
        body=fetch_stats(m.event_id); s=parse_stats(body) if body else {}; status="OK" if s else ("NO_BODY" if not body else "NOT_PARSED")
        prev=get_previous_values(m.event_id,m.minute,8) if s else None; p=calculate_goal_pressure(m,s,prev)
        if s:save_snapshot(m.event_id,StatsSnapshot(int(time.time()),m.minute,s))
        goals=parse_goal_timeline(fetch_summary(m.event_id)); qualifies,route,master,sc,hz=_evaluate(m,s,p,goals)
        ranked=sorted(sc.items(),key=lambda x:x[1],reverse=True); score_text=" ".join(f"{k}={v:.0f}" for k,v in ranked[:7])
        logger.info("LIVE_EVAL %d' %s — %s %d:%d | stats=%s | %s | MASTER=%.0f | P5=%.1f P10=%.1f P15=%.1f Pend=%.1f | %s %s",m.minute,m.home,m.away,m.home_score,m.away_score,status,score_text,master,*hz,"✅" if qualifies else "❌",route)
        now=time.time(); key=f"TRACK:{m.event_id}"; tracked=state.get(key); current=f"{m.home_score}:{m.away_score}"
        # Expose strategy diagnostics inside Telegram and journal without changing the existing formatter API.
        p.reasons.insert(0,f"Стратегии: {route} | общий рейтинг {master:.0f}/100")
        p.reasons.insert(1,f"Гол: 5м {hz[0]:.0f}% · 10м {hz[1]:.0f}% · 15м {hz[2]:.0f}% · до конца периода {hz[3]:.0f}%")
        if not tracked:
            if not qualifies:continue
            recs=unified_bot._recommendations(unified_bot._fetch_event_odds(m.event_id),m,p)
            if unified_bot.telegram_send(unified_bot._format_signal(m,p,s,recs,goals,"signal")):
                unified_bot._record_live(m,p,s,recs,"signal"); state[key]={"tracked_since":now,"ts":now,"score":current,"minute":m.minute,"pressure":p.score,"candidate_score":master,"route":route,"strategies":sc,"hazards":hz,"halftime_sent":m.is_halftime}; sent+=1
            continue
        changed=str(tracked.get("score",current))!=current; ht=m.is_halftime and not bool(tracked.get("halftime_sent")); last=float(tracked.get("ts",0)); last_master=float(tracked.get("candidate_score",0)); jump=qualifies and master>=last_master+10; follow=qualifies and now-last>=unified_bot.LIVE_COOLDOWN_MINUTES*60
        if changed or ht or jump or follow:
            reason="goal" if changed else "followup"; recs=unified_bot._recommendations(unified_bot._fetch_event_odds(m.event_id),m,p)
            if unified_bot.telegram_send(unified_bot._format_signal(m,p,s,recs,goals,reason)):
                unified_bot._record_live(m,p,s,recs,reason); tracked.update({"ts":now,"score":current,"minute":m.minute,"pressure":p.score,"candidate_score":master,"route":route,"strategies":sc,"hazards":hz,"halftime_sent":bool(tracked.get("halftime_sent")) or m.is_halftime}); state[key]=tracked; sent+=1
        else:
            tracked.update({"score":current,"minute":m.minute,"candidate_score":master,"route":route,"strategies":sc,"hazards":hz}); state[key]=tracked
    unified_bot._save_sent(state); logger.info("Отправлено LIVE-сигналов/обновлений: %d; сопровождается матчей: %d",sent,sum(1 for k in state if k.startswith("TRACK:"))); return sent

unified_bot.scan_live_once=scan_live_once_multi
