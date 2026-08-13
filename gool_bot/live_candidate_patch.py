"""Full multi-strategy LIVE engine with real market confirmation/value edge."""
from __future__ import annotations
import logging, math, time
import unified_bot
from bovada_live_odds import get_goal_total_odds
from live_engine import StatsSnapshot, calculate_goal_pressure, fetch_stats, fetch_summary, get_previous_values, parse_goal_timeline, parse_stats, save_snapshot
from match_history import analyse_history, fetch_match_history
logger=logging.getLogger("live_candidate_patch"); _HISTORY_CACHE={}; _HISTORY_CACHE_SECONDS=900

MAX_NEW_SIGNAL_MINUTE=75
MAX_FOLLOWUP_MINUTE=80
OBSERVE_MIN_SCORE=45
ENTRY_MIN_SCORE=60
STRONG_MIN_SCORE=70
FOLLOWUP_SCORE_JUMP=12
MIN_SANE_LIVE_ODD=1.05
MAX_SANE_LIVE_ODD=5.00
POST_GOAL_SETTLE_MINUTES=3


def _pair(s,k): a,b=s.get(k,(0.,0.)); return float(a),float(b)
def _total(s,k): return sum(_pair(s,k))
def _clamp(v): return round(max(0.,min(100.,v)),1)
def _signal_grade(master):
    if master>=STRONG_MIN_SCORE:return "STRONG"
    if master>=ENTRY_MIN_SCORE:return "ENTRY"
    if master>=OBSERVE_MIN_SCORE:return "OBSERVE"
    return "SILENT"
def _grade_rank(grade): return {"SILENT":0,"OBSERVE":1,"ENTRY":2,"STRONG":3}.get(str(grade or "SILENT"),0)

def _window_id(minute:int)->int:
    minute=max(1,min(90,int(minute or 1)))
    return (minute-1)//10

def _window_label(minute:int)->str:
    wid=_window_id(minute); start=wid*10+1; end=min(90,start+9)
    return f"{start}–{end}"

def _stats_baseline(s):
    return {k:round(_total(s,k),3) for k in ("xg","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")}

def _post_goal_activity(s, baseline):
    baseline=baseline or {}
    delta={k:max(0.,round(_total(s,k)-float(baseline.get(k,0) or 0),3)) for k in ("xg","shots","shots_on_target","big_chances","corners","shots_inside_box","touches_box")}
    evidence=0
    if delta["xg"]>=.18:evidence+=1
    if delta["shots"]>=2:evidence+=1
    if delta["shots_on_target"]>=1:evidence+=2
    if delta["big_chances"]>=1:evidence+=2
    if delta["corners"]>=2:evidence+=1
    if delta["shots_inside_box"]>=2:evidence+=1
    if delta["touches_box"]>=6:evidence+=1
    return evidence,delta

def _reentry_threshold(minute:int)->float:
    minute=int(minute or 0)
    if minute<=50:return 62.
    if minute<=60:return 64.
    if minute<=70:return 67.
    if minute<=80:return 72.
    return 101.

def _post_goal_reentry_ok(m,s,p,qualifies,route,master,tracked):
    if not tracked.get("post_goal_pending"):return True,{},"not_pending"
    goal_min=int(tracked.get("post_goal_minute",m.minute) or m.minute)
    since=max(0,int(m.minute)-goal_min)
    evidence,delta=_post_goal_activity(s,tracked.get("post_goal_stats") or {})
    threshold=_reentry_threshold(m.minute)
    grade=_signal_grade(master)
    remaining=max(0,90-int(m.minute))
    ok=(since>=POST_GOAL_SETTLE_MINUTES and remaining>=10 and qualifies and route!="REJECT" and grade in {"ENTRY","STRONG"} and master>=threshold and evidence>=2)
    reason=f"since={since}m evidence={evidence} master={master:.0f}/{threshold:.0f} remaining={remaining}"
    return ok,delta,reason

def _history(m):
    now=time.time(); c=_HISTORY_CACHE.get(m.event_id)
    if c and now-c[0]<_HISTORY_CACHE_SECONDS:return c[1],c[2]
    try:a=analyse_history(fetch_match_history(m.event_id,m.home,m.away,limit=5))
    except Exception as e: logger.info("HISTORY %s unavailable: %s",m.event_id,e); return 0.,{}
    valid=[x for x in (a.get("home",{}),a.get("away",{}),a.get("h2h",{})) if x.get("n",0)]
    if not valid:score=0.
    else:
        avg=float(a.get("historical_avg_total",0) or 0); score=_clamp(min(45,avg/4*45)+25*sum(float(x.get("over25",0) or 0) for x in valid)/len(valid)+18*sum(float(x.get("over35",0) or 0) for x in valid)/len(valid)+12*sum(float(x.get("over45",0) or 0) for x in valid)/len(valid))
    _HISTORY_CACHE[m.event_id]=(now,score,a); return score,a

def _dom(m,s):
    minute=max(1,m.minute); pace=min(1.45,45/minute) if minute<=45 else min(1.25,90/minute)
    return _clamp(min(25,_total(s,"shots")*pace/10*25)+min(25,_total(s,"shots_on_target")*pace/5*25)+min(18,_total(s,"xg")*pace/1.2*18)+min(12,(m.home_score+m.away_score)/2*12)+min(8,_total(s,"corners")*pace/5*8)+min(7,_total(s,"big_chances")*pace/2*7)+min(5,(_total(s,"shots_inside_box")*.22+_total(s,"touches_box")*.08)*pace))
def _threat(s):return _clamp(_total(s,"shots_inside_box")*4+_total(s,"touches_box")*1.2+_total(s,"corners")*4+_total(s,"big_chances")*13+_total(s,"shots_on_target")*5)
def _under(m,s):return _clamp(max(0,_total(s,"xg")-(m.home_score+m.away_score))*42+_total(s,"xg")*12+_total(s,"shots_on_target")*2)
def _fast(m,s,d,h):
    if m.minute>45 or m.is_halftime:return 0.
    pace=min(1.6,45/max(10,m.minute));return _clamp(d*.45+h*.15+min(100,_total(s,"shots")*pace*5)*.2+min(100,_total(s,"shots_on_target")*pace*10)*.2)
def _second(m,s,d,h,u):
    if m.minute<45:return 0.
    return _clamp(d*.30+h*.25+u*.25+min(100,_total(s,"shots_on_target")*10+_total(s,"corners")*4)*.20)
def _chase(m,s):
    if m.minute<55:return 0.
    if m.home_score==m.away_score:return 20.
    i=0 if m.home_score<m.away_score else 1; deficit=abs(m.home_score-m.away_score);return _clamp((20 if deficit==1 else 30)+_pair(s,"shots")[i]*4+_pair(s,"shots_on_target")[i]*9+_pair(s,"xg")[i]*18+_pair(s,"corners")[i]*4+_pair(s,"touches_box")[i]*1.1)
def _late(m,d,mom,ch,t,h):
    if m.minute<62:return 0.
    tf=min(100,max(0,(m.minute-60)*4));return _clamp(d*.22+mom*.22+ch*.22+t*.18+h*.08+tf*.08)
def _chaos(m,goals,mom,d):
    if not goals:return 0.
    try:last=max(int(str(x).split("'",1)[0]) for x in goals)
    except:return 0.
    since=max(0,m.minute-last); return 0. if since>15 else _clamp(max(0,100-since*6)*.45+mom*.30+d*.25)
def _side(s,i):return _clamp(_pair(s,"shots")[i]*3+_pair(s,"shots_on_target")[i]*8+_pair(s,"xg")[i]*20+_pair(s,"big_chances")[i]*12+_pair(s,"shots_inside_box")[i]*2+_pair(s,"touches_box")[i]*.8+_pair(s,"corners")[i]*3)
def _hazards(m,master):
    rate=(2.7/90)*(.45+1.35*master/100); vals=[(1-math.exp(-rate*x))*100 for x in (5,10,15)]; remain=(47-m.minute) if m.minute<=45 else (94-m.minute);vals.append((1-math.exp(-rate*max(0,remain)))*100);return tuple(round(min(92,x),1) for x in vals)

def _sane_price(row):
    try: odd=float(row.get("odd"))
    except (TypeError,ValueError,AttributeError): return False
    return MIN_SANE_LIVE_ODD <= odd <= MAX_SANE_LIVE_ODD

def _target_goal_markets(entries,m,p):
    goals=int(m.home_score)+int(m.away_score); targets=(goals+.5,goals+1.5)
    ls_rows=[r for r in unified_bot._recommendations(entries,m,p) if r.get("scope")=="FULL_TIME" and float(r.get("line",-99)) in targets and _sane_price(r)]
    ls_by_line={float(r["line"]):dict(r,source="LSApp") for r in ls_rows}
    try:bovada=get_goal_total_odds(m.home,m.away,m.home_score,m.away_score)
    except Exception as e:logger.info("Bovada target markets failed %s: %s",m.event_id,e); bovada=[]
    bov_by_line={}
    for r in bovada:
        line=float(r["line"])
        if _sane_price(r):bov_by_line[line]=r
        else:logger.info("BOVADA_PRICE_REJECTED %s %s — %s line=%.1f odd=%s",m.event_id,m.home,m.away,line,r.get("odd"))
    rows=[]
    for step,line in enumerate(targets,1):
        r=dict(bov_by_line.get(float(line)) or ls_by_line.get(float(line)) or {})
        if not r:continue
        r["goal_step"]=step; r["target_label"]="ещё 1 гол" if step==1 else "ещё 2 гола"
        odd=float(r["odd"]); conf=unified_bot._model_confidence(p.score,p.momentum,float(line),goals,"FULL_TIME",m.minute,odd)
        r["confidence"]=conf; r["value_edge"]=round(conf-(100/odd),1); rows.append(r)
    eligible=[r for r in rows if _sane_price(r)]
    if eligible:
        best=max(eligible,key=lambda r:(float(r.get("value_edge",-999)),int(r.get("confidence",0)),-int(r.get("goal_step",9)))); best["best_bet"]=True
    return rows

def _market(entries,m,p):
    recs=_target_goal_markets(entries,m,p)
    if not recs:return recs,{"available":False}
    r=next((x for x in recs if x.get("best_bet")),None)
    if r is None:return recs,{"available":False}
    odd=float(r["odd"]); raw=100/odd
    return recs,{"available":True,"scope":"FULL_TIME","line":r["line"],"odd":odd,"bookmakers":r.get("bookmakers",1),"source":r.get("source",""),"goal_step":r.get("goal_step"),"market_probability":round(raw,1)}

def _evaluate(m,s,p,goals,market):
    hist,_=_history(m);d=_dom(m,s);t=_threat(s);u=_under(m,s);f=_fast(m,s,d,hist);sec=_second(m,s,d,hist,u);ch=_chase(m,s);late=_late(m,d,p.momentum,ch,t,hist);chaos=_chaos(m,goals,p.momentum,d);home=_side(s,0);away=_side(s,1)
    sc={"MOMENTUM":p.score,"DOMINATION":d,"HISTORY":hist,"FAST_START":f,"SECOND_HALF":sec,"CHASE":ch,"LATE_GOAL":late,"POST_GOAL_CHAOS":chaos,"XG_UNDERPERFORMANCE":u,"THREAT":t,"HOME_PRESSURE":home,"AWAY_PRESSURE":away}
    ranked=sorted([(k,v) for k,v in sc.items() if v>0],key=lambda x:x[1],reverse=True); core=[x for x in ranked if x[0] not in ("HOME_PRESSURE","AWAY_PRESSURE")];top=core[:4]; master=_clamp(sum(v*w for (k,v),w in zip(top,(.40,.28,.20,.12))) if top else 0)
    hz=_hazards(m,master); model_period=hz[3]; edge=None; market_score=0.
    if market.get("available"):
        mp=float(market["market_probability"]); edge=round(model_period-mp,1); market_score=_clamp(50+edge*2); sc["MARKET_VALUE"]=market_score
    strong=[(k,v) for k,v in core if v>=72]; corroborated=[v for k,v in core if v>=64]; qualifies=bool(strong) or len(corroborated)>=3
    if edge is not None and edge<=-18 and len(strong)<2:qualifies=False
    if edge is not None and edge>=8 and len(corroborated)>=2:qualifies=True
    route="+".join(k for k,v in strong[:3]) if strong else ("MULTI_CONFIRM" if qualifies else "REJECT"); market.update({"model_period_probability":model_period,"edge_pp":edge,"market_value_score":market_score}); return qualifies,route,master,sc,hz,market

def _price_lines(recs,m):
    goals=int(m.home_score)+int(m.away_score); targets=(goals+.5,goals+1.5); by={float(r["line"]):r for r in recs if r.get("scope")=="FULL_TIME"}; lines=[]
    for step,line in enumerate(targets,1):
        r=by.get(float(line)); label="Ещё 1 гол" if step==1 else "Ещё 2 гола"
        if r and _sane_price(r):
            source=f" · {r.get('source')}" if r.get("source") else ""; lines.append(f"💰 {label}: <b>ТБ {line:g} — {float(r['odd']):.2f}</b>{source}")
        else:lines.append(f"💰 {label}: <b>ТБ {line:g} — нет адекватного LIVE-кэфа</b>")
    return "\n".join(lines)

def _format_strategy_signal(m,p,s,recs,goals,reason,route,master,hz,market):
    def pair(k):a,b=s.get(k,(0,0)); return f"{a:g}–{b:g}"
    status="Перерыв" if m.is_halftime else f"{m.minute}'"; grade=_signal_grade(master)
    if reason=="goal":
        if m.minute>MAX_FOLLOWUP_MINUTE:title="✅ <b>ГОЛ — СИГНАЛ СРАБОТАЛ!</b>"; action="🏁 <b>МАТЧ ЗАКРЫТ — ДАЛЬШЕ НЕ СЧИТАЮ</b>"
        else:title="✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>\n🔄 Матч и LIVE-линии пересчитаны"; action="✅ <b>ГОЛ ЗАФИКСИРОВАН</b>\n👀 <b>Новый вход пока не даю — начинаю новую оценку после гола</b>"
    elif reason=="reentry":title="♻️ <b>НОВЫЙ ВХОД ПОСЛЕ ГОЛА</b>"; action="🔥 <b>СТАТИСТИКА ПОСЛЕ ГОЛА СНОВА ПОДТВЕРЖДАЕТ ВХОД</b>"
    elif reason=="followup":title="🔄 <b>ОБНОВЛЕНИЕ ПО МАТЧУ</b>"
    elif m.is_halftime:title="🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>"
    else:title="🔴 <b>LIVE-СИГНАЛ</b>"
    if reason not in {"goal","reentry"}:
        if grade=="STRONG": action="🔥 <b>МОЖНО ЗАХОДИТЬ — СИЛЬНЫЙ СИГНАЛ</b>"
        elif grade=="ENTRY": action="🟡 <b>МОЖНО РАССМАТРИВАТЬ ВХОД</b>"
        elif grade=="OBSERVE": action="👀 <b>НАБЛЮДАЮ МАТЧ — ПОКА БЕЗ ВХОДА</b>"
        else: action="⚪ <b>СИГНАЛ ОСЛАБ — НОВЫЙ ВХОД НЕ НУЖЕН</b>"
        if m.is_halftime and grade in ("ENTRY","STRONG"): action += "\n🔵 Приоритет: ещё 1 гол во 2-м тайме"
    model_goal=max(1,min(92,round(hz[3]))); prices=_price_lines(recs,m); best=next((r for r in recs if r.get("best_bet") and _sane_price(r)),None)
    best_line=f"⭐ Лучшая ставка на матч: <b>ТБ {float(best['line']):g} @ {float(best['odd']):.2f}</b>" if best else "⭐ Лучшая ставка на матч: <b>сейчас нет адекватного LIVE-кэфа</b>"
    stats=f"📊 xG {pair('xg')} | Удары {pair('shots')} | В створ {pair('shots_on_target')}"
    return f"{title}\n\n⚽ <b>{m.home} — {m.away}</b>\n⏱ {status} | <b>{m.home_score}:{m.away_score}</b>\n🧩 Отрезок: <b>{_window_label(m.minute)} мин</b>\n\n{action}\n📈 Вероятность ещё гола: <b>{model_goal}%</b>\n{prices}\n{best_line}\n\n{stats}\n🧠 Рейтинг сигнала: <b>{master:.0f}/100</b>"

def _send(m,p,recs,text):return unified_bot.telegram_send_signal(m,p,recs,text)

async def scan_live_once_multi():
    live=await unified_bot.discover_live_matches();logger.info("Найдено LIVE-матчей: %d | FULL STRATEGY + REAL MARKET PIPELINE",len(live));state=unified_bot._load_sent();sent=0;ids={m.event_id for m in live}
    for k in list(state):
        if k.startswith("TRACK:") and k.split(":",1)[1] not in ids:state.pop(k,None)
    for m in live:
        body=fetch_stats(m.event_id);s=parse_stats(body) if body else {};status="OK" if s else ("NO_BODY" if not body else "NOT_PARSED");prev=get_previous_values(m.event_id,m.minute,8) if s else None;p=calculate_goal_pressure(m,s,prev)
        if s:save_snapshot(m.event_id,StatsSnapshot(int(time.time()),m.minute,s))
        goals=parse_goal_timeline(fetch_summary(m.event_id));entries=unified_bot._fetch_event_odds(m.event_id);recs,market=_market(entries,m,p);qualifies,route,master,sc,hz,market=_evaluate(m,s,p,goals,market);grade=_signal_grade(master);ranked=sorted(sc.items(),key=lambda x:x[1],reverse=True);score_text=" ".join(f"{k}={v:.0f}" for k,v in ranked[:8]);logger.info("LIVE_EVAL %d' W%s %s — %s %d:%d | stats=%s | %s | MASTER=%.0f GRADE=%s | %s %s",m.minute,_window_label(m.minute),m.home,m.away,m.home_score,m.away_score,status,score_text,master,grade,"✅" if qualifies else "❌",route)
        now=time.time();key=f"TRACK:{m.event_id}";tracked=state.get(key);current=f"{m.home_score}:{m.away_score}";window=_window_id(m.minute)
        if not tracked:
            if not qualifies or grade=="SILENT":continue
            if not m.is_halftime and m.minute>MAX_NEW_SIGNAL_MINUTE:logger.info("LATE_ENTRY_BLOCKED %d' %s — %s",m.minute,m.home,m.away);continue
            text=_format_strategy_signal(m,p,s,recs,goals,"signal",route,master,hz,market)
            if _send(m,p,recs,text):
                unified_bot._record_live(m,p,s,recs,"signal");state[key]={"tracked_since":now,"ts":now,"score":current,"minute":m.minute,"pressure":p.score,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"halftime_sent":m.is_halftime,"window":window,"post_goal_pending":False};sent+=1
            continue
        changed=str(tracked.get("score",current))!=current
        if changed:
            text=_format_strategy_signal(m,p,s,recs,goals,"goal",route,master,hz,market)
            if _send(m,p,recs,text):
                unified_bot._record_live(m,p,s,recs,"goal");sent+=1
                if m.minute>MAX_FOLLOWUP_MINUTE:
                    state.pop(key,None);logger.info("LATE_GOAL_TRACK_CLOSED %d' %s — %s | %s",m.minute,m.home,m.away,current);continue
                tracked.update({"ts":now,"score":current,"minute":m.minute,"pressure":p.score,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"halftime_sent":bool(tracked.get("halftime_sent")) or m.is_halftime,"window":window,"post_goal_pending":True,"post_goal_minute":m.minute,"post_goal_score":current,"post_goal_stats":_stats_baseline(s)})
                state[key]=tracked
            continue
        if tracked.get("post_goal_pending"):
            reentry_ok,delta,reentry_reason=_post_goal_reentry_ok(m,s,p,qualifies,route,master,tracked)
            logger.info("POST_GOAL_REVIEW %d' W%s %s — %s | %s | delta=%s | %s",m.minute,_window_label(m.minute),m.home,m.away,"ENTRY" if reentry_ok else "WAIT",delta,reentry_reason)
            if reentry_ok:
                text=_format_strategy_signal(m,p,s,recs,goals,"reentry",route,master,hz,market)
                if _send(m,p,recs,text):
                    unified_bot._record_live(m,p,s,recs,"signal");sent+=1
                    tracked.update({"ts":now,"minute":m.minute,"pressure":p.score,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"window":window,"post_goal_pending":False,"last_reentry_minute":m.minute})
                    state[key]=tracked
            else:
                tracked.update({"score":current,"minute":m.minute,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"window":window});state[key]=tracked
            continue
        last=float(tracked.get("ts",0));lastm=float(tracked.get("candidate_score",0));last_grade=str(tracked.get("grade") or _signal_grade(lastm));cooldown_ok=now-last>=unified_bot.LIVE_COOLDOWN_MINUTES*60
        upgraded=_grade_rank(grade)>_grade_rank(last_grade);jump=qualifies and grade!="SILENT" and master>=lastm+FOLLOWUP_SCORE_JUMP and cooldown_ok;halftime_new=m.is_halftime and not bool(tracked.get("halftime_sent")) and grade!="SILENT";window_changed=window!=int(tracked.get("window",window));ordinary_update=(upgraded or jump or halftime_new) and cooldown_ok
        should_send=m.minute<=MAX_FOLLOWUP_MINUTE and ordinary_update
        if should_send:
            if not qualifies or grade=="SILENT" or route=="REJECT":continue
            text=_format_strategy_signal(m,p,s,recs,goals,"followup",route,master,hz,market)
            if _send(m,p,recs,text):
                unified_bot._record_live(m,p,s,recs,"followup");sent+=1;tracked.update({"ts":now,"score":current,"minute":m.minute,"pressure":p.score,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"halftime_sent":bool(tracked.get("halftime_sent")) or m.is_halftime,"window":window});state[key]=tracked
        else:
            if window_changed:logger.info("TEN_MIN_WINDOW %s — %s -> %s | master %.0f grade %s",m.home,m.away,_window_label(m.minute),master,grade)
            tracked.update({"score":current,"minute":m.minute,"candidate_score":master,"grade":grade,"route":route,"strategies":sc,"hazards":hz,"market":market,"window":window});state[key]=tracked
    unified_bot._save_sent(state);logger.info("Отправлено LIVE-сигналов/обновлений: %d; сопровождается матчей: %d",sent,sum(1 for k in state if k.startswith("TRACK:")));return sent

unified_bot.scan_live_once=scan_live_once_multi
