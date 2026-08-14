"""Route confirmed CORE wins through the selected gold meme-cat result card."""
import telegram_image_signal_patch as tip
from multi_engine_card import render_engine_card

_original=tip.render_signal_card

def _render(match,pressure,recs=None,kind="entry",master=None,probabilities=None):
    if kind=="goal":
        score=float(master if master is not None else getattr(pressure,"score",0) or 0)
        return render_engine_card(match,"core",score,{},None,"win")
    return _original(match,pressure,recs,kind=kind,master=master,probabilities=probabilities)

tip.render_signal_card=_render
