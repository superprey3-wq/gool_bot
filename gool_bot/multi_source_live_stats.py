"""Resolve missing LIVE football statistics across independent providers.

Priority is field-by-field: Flashscore -> FotMob -> GOAL API -> 365Scores.
Providers are never added together. Provenance is returned so cards/logs can
say where each metric came from.
"""
from __future__ import annotations

import copy
import logging

import candidate_enrichment_patch as ce
import scores365_enrichment_patch as s365

logger = logging.getLogger("multi_source_live_stats")


def _pair_total(stats, key):
    try:
        a, b = stats.get(key, (0, 0))
        return float(a or 0) + float(b or 0)
    except Exception:
        return 0.0


def _pair(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:return float(value[0] or 0), float(value[1] or 0)
        except Exception:return None
    return None


def _scalar(value):
    try:
        if value in (None, "", "-"):return None
        return float(value)
    except Exception:return None


def _node_total(value):
    if value is None:return None
    p=_pair(value)
    if p:return p[0]+p[1]
    if isinstance(value,dict):
        vals=[]
        for k in ("home","away","homeValue","awayValue","value"):
            v=_scalar(value.get(k))
            if v is not None:vals.append(v)
        if vals:return sum(vals[:2])
    if isinstance(value,list):
        vals=[_scalar(v) for v in value];vals=[v for v in vals if v is not None]
        if vals:return sum(vals[:2])
    return _scalar(value)


def _goal_metric(gs,*names):
    for name in names:
        p=_pair(gs.get(name))
        if p and (p[0]>0 or p[1]>0):return p
    return None


def provider_payload(match):
    try:goal=ce._goal_stats(match)
    except Exception as exc:
        logger.debug("GOAL stats fallback failed %s: %s",getattr(match,"event_id",""),exc);goal={"matched":False}
    try:fot=ce._fotmob_features(match)
    except Exception as exc:
        logger.debug("FotMob stats fallback failed %s: %s",getattr(match,"event_id",""),exc);fot={"matched":False}
    try:sx=s365._features(match)
    except Exception as exc:
        logger.debug("365Scores stats fallback failed %s: %s",getattr(match,"event_id",""),exc);sx={"matched":False}
    return {"goal_api":goal or {},"fotmob":fot or {},"scores365":sx or {}}


def enrich(stats,match=None,providers=None):
    out=copy.deepcopy(stats or {})
    provenance={k:"Flashscore" for k in out if not str(k).startswith("_") and _pair_total(out,k)>0}
    providers=providers or (provider_payload(match) if match is not None else {})
    goal=providers.get("goal_api") or {};gs=(goal.get("stats") or {}) if isinstance(goal,dict) else {}
    fot=providers.get("fotmob") or {};ff=(fot.get("features") or {}) if isinstance(fot,dict) else {}
    sx=providers.get("scores365") or {}

    # xG / xGoT: Flashscore -> FotMob -> 365Scores (GOAL currently has no parsed xG field).
    if _pair_total(out,"xg")<=0:
        fv=_scalar(ff.get("shot_xg_total"));sv=_scalar(sx.get("shot_xg_total"))
        if fv is not None and fv>0:out["xg"]=(round(fv,3),0.0);provenance["xg"]="FotMob"
        elif sv is not None and sv>0:out["xg"]=(round(sv,3),0.0);provenance["xg"]="365Scores"
    if _pair_total(out,"xgot")<=0:
        fv=_scalar(ff.get("shot_xgot_total"));sv=_scalar(sx.get("shot_xgot_total"))
        if fv is not None and fv>0:out["xgot"]=(round(fv,3),0.0);provenance["xgot"]="FotMob"
        elif sv is not None and sv>0:out["xgot"]=(round(sv,3),0.0);provenance["xgot"]="365Scores"

    # Shots: Flashscore -> FotMob shotmap -> GOAL API -> 365Scores.
    if _pair_total(out,"shots")<=0:
        fshots=int(ff.get("shotmap_n") or 0);gshots=_goal_metric(gs,"total shots","shots","shots total");sshots=int(sx.get("shots") or 0)
        if fshots>0:out["shots"]=(float(fshots),0.0);provenance["shots"]="FotMob"
        elif gshots:out["shots"]=gshots;provenance["shots"]="GOAL API"
        elif sshots>0:out["shots"]=(float(sshots),0.0);provenance["shots"]="365Scores"

    # Shots on target: Flashscore -> GOAL API. Other providers are used only when
    # their adapters expose a trustworthy SOT field in the future.
    if _pair_total(out,"shots_on_target")<=0:
        p=_goal_metric(gs,"on target","shots on goal","shots on target")
        if p:out["shots_on_target"]=p;provenance["shots_on_target"]="GOAL API"

    # Big chances: Flashscore -> FotMob -> GOAL API.
    if _pair_total(out,"big_chances")<=0:
        fv=_node_total(ff.get("big_chances_node"));gp=_goal_metric(gs,"big chances","big chance")
        if fv is not None and fv>0:out["big_chances"]=(fv,0.0);provenance["big_chances"]="FotMob"
        elif gp:out["big_chances"]=gp;provenance["big_chances"]="GOAL API"

    # Box activity: keep true shots-inside-box distinct from touches-in-box.
    if _pair_total(out,"shots_inside_box")<=0:
        gp=_goal_metric(gs,"shots inside box","shots inside the box")
        if gp:out["shots_inside_box"]=gp;provenance["shots_inside_box"]="GOAL API"
    if _pair_total(out,"touches_box")<=0:
        fv=_node_total(ff.get("touches_box_node"));gp=_goal_metric(gs,"touches in opposition box","touches in box")
        if fv is not None and fv>0:out["touches_box"]=(fv,0.0);provenance["touches_box"]="FotMob"
        elif gp:out["touches_box"]=gp;provenance["touches_box"]="GOAL API"

    out["_metric_sources"]=provenance
    out["_provider_presence"]={
        "Flashscore":bool(stats),
        "FotMob":bool(fot.get("matched") and ff),
        "GOAL API":bool(goal.get("matched") and gs),
        "365Scores":bool(sx.get("matched") and (sx.get("shots") or sx.get("shot_xg_total") is not None or sx.get("has_stats"))),
    }
    return out,provenance,providers


def source_label(stats,key):return str((stats or {}).get("_metric_sources",{}).get(key) or "")

logger.info("Multi-source LIVE stats resolver active | strict priority Flashscore -> FotMob -> GOAL -> 365")
