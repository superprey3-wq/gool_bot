"""Keep CORE signal success separate from the recommended market result."""
from __future__ import annotations
import logging
import report_now
from market_settlement import settle_primary

logger=logging.getLogger("core_report_truth_patch")
_WIN={"+","win","won"}
_LOSS={"-","loss","lost"}
_PUSH={"push","void","return","возврат"}
_PENDING={"","pending","wait","waiting"}


def _norm(v):
    return str(v or "").strip().lower()


def _market_pnl(row,state):
    for key in ("bet_pnl_units","pnl_units"):
        try:
            v=row.get(key)
            if v is not None:return float(v)
        except (TypeError,ValueError):pass
    try:odd=float(row.get("bet_settled_odd") or row.get("odd") or (row.get("primary") or {}).get("odd") or 0)
    except (TypeError,ValueError):odd=0.0
    if state=="win" and odd>1:return odd-1.0
    if state=="loss":return -1.0
    if state=="push":return 0.0
    return None


def _core_state(row):
    # Never use row['result'] here: that field is CORE next-goal truth and may be
    # a win even when the concrete recommended market loses.
    br=_norm(row.get("bet_result"))
    if br in _WIN:return "win",_market_pnl(row,"win")
    if br in _LOSS:return "loss",_market_pnl(row,"loss")
    if br in _PUSH:return "push",0.0

    final=row.get("final_score")
    primary=row.get("primary")
    if final and isinstance(primary,dict):
        settlement=settle_primary(primary,str(final)) or {}
        r=_norm(settlement.get("result"))
        try:p=float(settlement.get("pnl_units",0) or 0)
        except (TypeError,ValueError):p=0.0
        if r in _WIN:return "win",p
        if r in _LOSS:return "loss",p
        if r in _PUSH:return "push",p
    return "pending",None


report_now._core_state=_core_state
logger.info("CORE_REPORT_TRUTH enabled: reports use concrete market settlement only")
