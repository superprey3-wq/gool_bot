"""Competition-aware priors for GOOL LIVE.

Profiles are deliberately data-driven where possible: recent same-competition
matches are blended with a conservative competition-type prior.  Sparse leagues
shrink toward the global baseline instead of receiving extreme hand-tuned scores.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import re

GLOBAL_GOALS=2.65

@dataclass(frozen=True)
class LeagueProfile:
    kind:str
    observed_n:int
    observed_avg_goals:float|None
    blended_avg_goals:float
    volatility:float
    reliability:float
    goal_rate_multiplier:float
    late_multiplier:float
    first_half_multiplier:float


def _norm(s):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(s or "").lower()).split())

def competition_kind(name:str)->str:
    s=_norm(name)
    if any(x in s for x in ("friendly","friendlies","club friendly","international friendly")):return "friendly"
    if any(x in s for x in ("qualification","qualifying","preliminary")):return "qualifier"
    if any(x in s for x in ("play off","playoff","relegation","promotion")):return "playoff"
    if any(x in s for x in ("cup","copa","pokal","trophy","knockout")):return "cup"
    if any(x in s for x in ("u17","u18","u19","u20","u21","u23","youth","reserve")):return "youth"
    if any(x in s for x in ("women","wsl","feminine","femenina")):return "women"
    return "league"

# Priors are intentionally mild; observed same-competition results dominate as n grows.
_KIND_PRIOR={
    "league":(2.65,1.00,1.00,1.00,1.00),
    "cup":(2.75,1.12,1.02,1.06,0.82),
    "playoff":(2.45,1.15,0.93,1.04,0.80),
    "qualifier":(2.55,1.10,0.96,1.03,0.78),
    "friendly":(3.00,1.30,1.08,1.08,0.62),
    "youth":(3.15,1.28,1.12,1.10,0.68),
    "women":(2.95,1.18,1.08,1.07,0.72),
}

def build_profile(competition:str,same_comp_rows=None)->LeagueProfile:
    rows=list(same_comp_rows or [])
    kind=competition_kind(competition)
    prior,vol,fh,late,base_rel=_KIND_PRIOR[kind]
    totals=[float(getattr(r,"total",0) or 0) for r in rows if getattr(r,"total",None) is not None]
    n=len(totals);obs=(sum(totals)/n) if n else None
    # Eight pseudo-observations prevent tiny samples from creating absurd league effects.
    blended=(prior*8+(obs or prior)*n)/(8+n)
    reliability=min(1.0,base_rel*(0.55+0.45*min(1.0,n/16.0)))
    rate=max(.78,min(1.24,blended/GLOBAL_GOALS))
    # High-scoring observed competitions get a modest late/first-half adjustment too.
    obs_factor=max(.90,min(1.12,rate))
    return LeagueProfile(kind,n,round(obs,3) if obs is not None else None,round(blended,3),vol,round(reliability,3),round(rate,3),round(late*obs_factor,3),round(fh*obs_factor,3))

def to_dict(p:LeagueProfile)->dict:return asdict(p)
