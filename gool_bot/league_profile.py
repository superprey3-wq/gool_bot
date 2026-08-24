"""Competition-aware priors for GOOL LIVE.

Recent same-competition results and a persistent historical timing store are
blended with mild competition-type priors. Sparse leagues shrink toward the
global baseline instead of receiving extreme hand-tuned scores.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import re
from league_timing_store import profile as timing_profile

GLOBAL_GOALS=2.65
GLOBAL_FH_GPM=1.15
GLOBAL_LATE_GPM=0.55

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
    timing_matches:int=0
    timing_late_gpm:float|None=None
    timing_first_half_gpm:float|None=None


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
    prior,vol,fh_prior,late_prior,base_rel=_KIND_PRIOR[kind]
    totals=[float(getattr(r,"total",0) or 0) for r in rows if getattr(r,"total",None) is not None]
    n=len(totals);obs=(sum(totals)/n) if n else None
    historical=timing_profile(competition)
    hn=int(historical.get("matches",0) or 0)
    hist_gpm=historical.get("goals_per_match")
    # Eight pseudo-observations protect small samples; historical timing data can dominate when broad.
    numerator=prior*8+(obs or prior)*n
    denominator=8+n
    if hn and hist_gpm is not None:
        hw=min(40,hn)
        numerator+=float(hist_gpm)*hw;denominator+=hw
    blended=numerator/denominator
    evidence_n=n+min(hn,40)
    reliability=min(1.0,base_rel*(0.50+0.50*min(1.0,evidence_n/24.0)))
    rate=max(.76,min(1.26,blended/GLOBAL_GOALS))
    obs_factor=max(.90,min(1.12,rate))
    fh=fh_prior*obs_factor;late=late_prior*obs_factor
    late_gpm=historical.get("late_goals_per_match")
    fh_gpm=historical.get("first_half_goals_per_match")
    # Once timing has real depth, use actual phase rates rather than inferring them from total scoring.
    if hn>=20 and late_gpm is not None:
        timing_rel=min(1.0,hn/80.0)
        measured=max(.72,min(1.32,float(late_gpm)/GLOBAL_LATE_GPM))
        late=late*(1-timing_rel)+measured*timing_rel
    if hn>=20 and fh_gpm is not None:
        timing_rel=min(1.0,hn/80.0)
        measured=max(.75,min(1.28,float(fh_gpm)/GLOBAL_FH_GPM))
        fh=fh*(1-timing_rel)+measured*timing_rel
    return LeagueProfile(kind,n,round(obs,3) if obs is not None else None,round(blended,3),vol,round(reliability,3),round(rate,3),round(late,3),round(fh,3),hn,round(float(late_gpm),3) if late_gpm is not None else None,round(float(fh_gpm),3) if fh_gpm is not None else None)

def to_dict(p:LeagueProfile)->dict:return asdict(p)
