"""Route GOOL CORE entry and confirmed-win cards through the approved gold concept.

This keeps the working signal logic untouched and changes only the visual renderer:
- entry -> gold CORE frame
- confirmed goal -> gold meme-cat ZAHOD frame
HT HUNTER and LATE RISK already use their own blue/red renderer paths.
"""
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

def _render(match,pressure,recs=None,kind="entry",master=None,probabilities=None):
    score=float(master if master is not None else getattr(pressure,"score",0) or 0)
    if kind=="goal":
        return render_engine_card(match,"core",score,{},None,"win")
    if kind=="entry":
        return render_engine_card(match,"core",score,{},_best_odd(recs),None)
    return _original(match,pressure,recs,kind=kind,master=master,probabilities=probabilities)

tip.render_signal_card=_render
