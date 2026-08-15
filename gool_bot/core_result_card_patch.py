"""Route GOOL CORE entry and confirmed-win cards through the approved gold concept."""
import telegram_image_signal_patch as tip
from multi_engine_card import render_engine_card

_original=tip.render_signal_card

def _best_odd(recs):
    rows=list(recs or [])
    best=next((r for r in rows if r.get("best_bet")),None) or next((r for r in rows if r.get("full_match_best")),None) or next((r for r in rows if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)
    if not best:return None
    try:
        odd=float(best.get("odd",0) or 0)
        return odd if odd>1 else None
    except Exception:return None

def _pair(stats,key):
    try:
        a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
    except Exception:return 0.0,0.0

def _visual_stats(pressure):
    stats=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {}
    xg=_pair(stats,"xg");shots=_pair(stats,"shots");sot=_pair(stats,"shots_on_target")
    out={}
    if xg!=(0.0,0.0):out["xg_total"]=f"{sum(xg):.2f}"
    if shots!=(0.0,0.0):out["shots_pair"]=f"{shots[0]:g}-{shots[1]:g}"
    if sot!=(0.0,0.0):out["sot_pair"]=f"{sot[0]:g}-{sot[1]:g}"
    return out

def _render(match,pressure,recs=None,kind="entry",master=None,probabilities=None):
    score=float(master if master is not None else getattr(pressure,"score",0) or 0)
    if kind=="goal":return render_engine_card(match,"core",score,{},None,"win")
    if kind=="entry":return render_engine_card(match,"core",score,_visual_stats(pressure),_best_odd(recs),None)
    return _original(match,pressure,recs,kind=kind,master=master,probabilities=probabilities)

tip.render_signal_card=_render
