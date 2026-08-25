"""Make SECOND_HALF_OVER15 card explanation match HT/recovery decision mode."""
from __future__ import annotations

import re
import multi_engine_card as mec

_orig_why = mec._why


def _source_phrase(delta):
    names=[]
    prov=delta.get("_metric_sources") or {}
    for src in prov.values():
        s=str(src or "").strip()
        if s and s not in names:
            names.append(s)
    ext=delta.get("_external_validation") or {}
    goal=ext.get("goal_api") or {}
    if goal.get("matched") and goal.get("stats") and "GOAL API" not in names: names.append("GOAL API")
    fot=ext.get("fotmob_deep") or ext.get("fotmob") or {}; ff=fot.get("features") or {}
    if fot.get("matched") and (ff.get("shotmap_n") or ff.get("shot_xg_total") is not None) and "FotMob" not in names: names.append("FotMob")
    s365=ext.get("scores365_deep") or ext.get("scores365") or {}
    if s365.get("matched") and (s365.get("shots") or s365.get("shot_xg_total") is not None or s365.get("has_stats")) and "365Scores" not in names: names.append("365Scores")
    if not names: return ""
    return "Источники: "+", ".join(names[:4])+"."


def _why(engine, score, delta, timing):
    if engine != "second_half_over15":
        return _orig_why(engine, score, delta, timing)

    xg=float(delta.get("xg",0) or 0); xgot=float(delta.get("xgot",0) or 0)
    shots=int(round(float(delta.get("shots",0) or 0))); sot=int(round(float(delta.get("shots_on_target",0) or 0)))
    big=int(round(float(delta.get("big_chances",0) or 0))); inside=int(round(float(delta.get("shots_inside_box",0) or 0)))
    reason=str(delta.get("_decision_reason") or "")
    m=re.search(r"evidence=(\d+)(?:/(\d+))?",reason); evidence=int(m.group(1)) if m else 0
    gate=re.search(r"gate=(\d+)/(\d+)",reason)

    if "recovery=46-55" not in reason:
        needed=int(m.group(2)) if m and m.group(2) else 4
        mode=f"HT: полный 1-й тайм; критерии {evidence}/{needed}."
    elif gate and int(gate.group(1))>=82:
        mode=f"51–55′: поздний фильтр GOOL ≥82, подтверждений ≥{gate.group(2)}; пройдено {evidence}."
    else:
        need=gate.group(2) if gate else "5"
        mode=f"46–50′ recovery: GOOL ≥78, подтверждений ≥{need}; пройдено {evidence}."

    stats=f"LIVE: xG {xg:.2f}, xGoT {xgot:.2f}, удары {shots}, в створ {sot}, big chances {big}, штрафная {inside}."
    score_text=f"GOOL {float(score):.0f}/100. Коэффициенты не влияют на решение."
    src=_source_phrase(delta)
    return " ".join(x for x in (mode,stats,score_text,src) if x)


mec._why=_why
