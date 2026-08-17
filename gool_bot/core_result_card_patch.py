"""Route GOOL CORE entry and confirmed-win cards through the approved gold concept."""
import telegram_image_signal_patch as tip
from multi_engine_card import render_engine_card
from goal_timing import context as timing_context
_original=tip.render_signal_card

def _best_odd(recs):
    rows=list(recs or []);best=next((r for r in rows if r.get("best_bet")),None) or next((r for r in rows if r.get("full_match_best")),None) or next((r for r in rows if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)
    if not best:return None
    try:
        odd=float(best.get("odd",0) or 0);return odd if odd>1 else None
    except:return None

def _pair(stats,key):
    try:a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
    except:return 0.0,0.0

def _xbet_score(game,fh,fa):
    """Use 1xBet full score when exposed unambiguously; otherwise keep synced Flashscore score."""
    try:
        sc=game.get("SC") or {};fs=sc.get("FS") or {}
        h=fs.get("S1");a=fs.get("S2")
        if h is not None and a is not None:return int(h),int(a)
    except Exception:pass
    return int(fh),int(fa)

def _market_snapshot(match):
    """Best-effort 1xBet snapshot for card rendering. Never affects CORE logic."""
    try:
        from xbet_live_odds import fetch_live_football,match_event,fetch_game
        from xbet_market_decoder import decode
        events,root,err,attempts=fetch_live_football()
        if not events:return {}
        event,sim,rev=match_event(str(getattr(match,"home","")),str(getattr(match,"away","")),events)
        if not event or float(sim or 0)<0.62:return {}
        game,game_root,game_err,game_attempts=fetch_game(event.get("I"),root)
        if not game:return {}
        minute=int(getattr(match,"minute",0) or 0)
        fh=int(getattr(match,"home_score",0) or 0);fa=int(getattr(match,"away_score",0) or 0)
        sh,sa=_xbet_score(game,fh,fa);goals=sh+sa
        d=decode(game,goals,minute)
        out={"source":"1xBet","target":d.get("target")}
        half=d.get("half") or {}
        if half:
            out["half_over"]=(half.get("over") or {}).get("C")
            out["half_under"]=(half.get("under") or {}).get("C")
        full=d.get("full") or {}
        target=float(d.get("target",goals+0.5))
        if target in full:
            p=full[target];out["next_over"]=(p.get("over") or {}).get("C");out["next_under"]=(p.get("under") or {}).get("C")
        best=None
        for line,p in full.items():
            try:o=float((p.get("over") or {}).get("C"));u=float((p.get("under") or {}).get("C"))
            except:continue
            cand=(abs(o-u),float(line),o,u)
            if best is None or cand[0]<best[0]:best=cand
        if best:out.update({"main_line":best[1],"main_over":best[2],"main_under":best[3]})
        # BTTS is already settled once both teams have scored. Never show live
        # BTTS prices in that state, even if 1xBet exposes another G=22 pair.
        if sh>0 and sa>0:
            out["btts_settled"]=True
        else:
            y,n=d.get("btts_yes"),d.get("btts_no")
            if y:out["btts_yes"]=y.get("C")
            if n:out["btts_no"]=n.get("C")
        return out
    except Exception:
        return {}

def _fresh_stats(match):
    """Fetch the same authoritative Flashscore stats used by GOOL right before card render."""
    try:
        from live_engine import fetch_stats,parse_stats
        body=fetch_stats(str(getattr(match,"event_id","") or ""))
        return parse_stats(body) if body else {}
    except Exception:return {}

def _visual_stats(match,pressure):
    stats=_fresh_stats(match) or getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {}
    out={"_timing":timing_context(match,"core"),"_xbet":_market_snapshot(match)}
    xg=_pair(stats,"xg");shots=_pair(stats,"shots");sot=_pair(stats,"shots_on_target")
    danger=_pair(stats,"dangerous_attacks");touch=_pair(stats,"touches_box")
    if xg!=(0.0,0.0):out["xg"]=round(sum(xg),2)
    if shots!=(0.0,0.0):out["shots"]=round(sum(shots),0)
    if sot!=(0.0,0.0):out["shots_on_target"]=round(sum(sot),0)
    if danger!=(0.0,0.0):out["touches_box"]=round(sum(danger),0)
    elif touch!=(0.0,0.0):out["touches_box"]=round(sum(touch),0)
    return out

def _render(match,pressure,recs=None,kind="entry",master=None,probabilities=None):
    score=float(master if master is not None else getattr(pressure,"score",0) or 0)
    if kind=="goal":return render_engine_card(match,"core",score,{},None,"win")
    if kind=="entry":return render_engine_card(match,"core",score,_visual_stats(match,pressure),_best_odd(recs),None)
    return _original(match,pressure,recs,kind=kind,master=master,probabilities=probabilities)
tip.render_signal_card=_render
