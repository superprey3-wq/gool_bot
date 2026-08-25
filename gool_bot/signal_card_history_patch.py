"""Expose the prematch calibration used by the best-market selector on CORE cards."""
from __future__ import annotations
import signal_card

_orig_reason=signal_card._reason

def _reason(pressure,recs,probs):
    text=_orig_reason(pressure,recs,probs)
    best=signal_card._best(recs or [])
    if not isinstance(best,dict):return text
    try:rate=float(best.get("history_market_rate"));weight=float(best.get("history_weight") or 0)*100
    except (TypeError,ValueError):return text
    if weight<=0:return text
    prematch=f"Предматч: близкая линия проходила {rate:.0f}% по форме/H2H; вес {weight:.0f}%."
    return f"{prematch} {text}"

signal_card._reason=_reason
