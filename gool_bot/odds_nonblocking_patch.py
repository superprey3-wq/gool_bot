"""Make market odds informational only for GOOL signal eligibility.

The underlying analytical stack may still compute/display market probability,
edge and a concrete bet for the card, but prices must never create, strengthen
or cancel a signal. Eligibility is rebuilt only from analytical score blocks.
"""
from __future__ import annotations
import logging
import live_candidate_patch as lc

logger=logging.getLogger("odds_nonblocking")
_orig_evaluate=lc._evaluate

_ANALYTIC_EXCLUDE={"HOME_PRESSURE","AWAY_PRESSURE","MARKET_VALUE"}

def _evaluate(match,stats,pressure,goals,market):
    qualifies,route,master,scores,hazards,market=_orig_evaluate(match,stats,pressure,goals,market)
    # Preserve explicit non-market analytical vetoes from enrichment layers.
    if str(route or "").upper() in {"EXTERNAL_CONFLICT","LEAGUE_REJECT","CONTEXT_REJECT"}:
        return qualifies,route,master,scores,hazards,market
    core=[(k,float(v)) for k,v in (scores or {}).items()
          if k not in _ANALYTIC_EXCLUDE and isinstance(v,(int,float)) and float(v)>0]
    strong=[(k,v) for k,v in core if v>=72]
    corroborated=[(k,v) for k,v in core if v>=64]
    stat_qualifies=bool(strong) or len(corroborated)>=3
    if stat_qualifies:
        route="+".join(k for k,_ in sorted(strong,key=lambda x:x[1],reverse=True)[:3]) or "MULTI_CONFIRM"
    else:
        route="REJECT"
    if isinstance(market,dict):
        market["odds_informational_only"]=True
    return stat_qualifies,route,master,scores,hazards,market

lc._evaluate=_evaluate
logger.info("Odds are display-only: signal eligibility is analytics-only")
