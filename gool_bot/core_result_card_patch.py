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

def _visual_stats(match,pressure):
    stats=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {};out={"_timing":timing_context(match,"core")}
    xg=_pair(stats,"xg");shots=_pair(stats,"shots");sot=_pair(stats,"shots_on_target");touch=_pair(stats,"touches_box")
    if xg!=(0.0,0.0):out["xg"]=round(sum(xg),2)
    if shots!=(0.0,0.0):out["shots"]=round(sum(shots),0)
    if sot!=(0.0,0.0):out["shots_on_target"]=round(sum(sot),0)
    if touch!=(0.0,0.0):out["touches_box"]=round(sum(touch),0)
    return out

def _render(match,pressure,recs=None,kind="entry",master=None,probabilities=None):
    score=float(master if master is not None else getattr(pressure,"score",0) or 0)
    if kind=="goal":return render_engine_card(match,"core",score,{},None,"win")
    if kind=="entry":return render_engine_card(match,"core",score,_visual_stats(match,pressure),_best_odd(recs),None)
    return _original(match,pressure,recs,kind=kind,master=master,probabilities=probabilities)
tip.render_signal_card=_render
