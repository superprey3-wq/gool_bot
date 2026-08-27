"""Production policy: send only stronger CORE entries and re-entries."""
from __future__ import annotations
import logging
import live_candidate_patch as lc

logger=logging.getLogger("strict_signal_policy_patch")

# Slightly tighten internal grades. ENTRY remains useful for internal tracking,
# but only STRONG is user-facing after this patch.
lc.ENTRY_MIN_SCORE=65
lc.STRONG_MIN_SCORE=75

_orig_format=lc._format_strategy_signal

def _format_strategy_signal(m,p,s,recs,goals,reason,route,master,hz,market):
    grade=lc._signal_grade(master)
    if reason in {"signal","reentry"} and grade!="STRONG":
        logger.info(
            "STRICT_SIGNAL_SUPPRESS %s %d' %s — %s | grade=%s master=%.0f",
            reason,int(getattr(m,"minute",0) or 0),getattr(m,"home",""),
            getattr(m,"away",""),grade,float(master or 0),
        )
        return ""
    return _orig_format(m,p,s,recs,goals,reason,route,master,hz,market)

lc._format_strategy_signal=_format_strategy_signal
