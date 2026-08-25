"""Make SECOND_HALF_OVER15 card explanation match HT/recovery decision mode."""
from __future__ import annotations

import re
import multi_engine_card as mec

_orig_why = mec._why


def _why(engine, score, delta, timing):
    if engine != "second_half_over15":
        return _orig_why(engine, score, delta, timing)

    xg = float(delta.get("xg", 0) or 0)
    xgot = float(delta.get("xgot", 0) or 0)
    shots = int(round(float(delta.get("shots", 0) or 0)))
    sot = int(round(float(delta.get("shots_on_target", 0) or 0)))
    big = int(round(float(delta.get("big_chances", 0) or 0)))
    inside = int(round(float(delta.get("shots_inside_box", 0) or 0)))
    reason = str(delta.get("_decision_reason") or "")

    m = re.search(r"evidence=(\d+)(?:/(\d+))?", reason)
    evidence = int(m.group(1)) if m else 0
    gate = re.search(r"gate=(\d+)/(\d+)", reason)

    if "recovery=46-55" not in reason:
        mode = "Решение принято на перерыве по полному 1-му тайму."
        needed = int(m.group(2)) if m and m.group(2) else 4
        gate_text = f"Для HT пройдено {evidence}/{needed} LIVE-критериев."
    elif gate and int(gate.group(1)) >= 82:
        mode = "Сигнал рассчитан в позднем окне 51–55′: статистика 1-го тайма подтверждена стартом 2-го тайма."
        gate_text = f"Поздний фильтр усилен: GOOL ≥82 и минимум {gate.group(2)} подтверждений; пройдено {evidence}."
    else:
        mode = "HT был пропущен циклом; сигнал восстановлен в контрольном окне 46–50′."
        need = gate.group(2) if gate else "5"
        gate_text = f"Recovery-фильтр: GOOL ≥78 и минимум {need} подтверждений; пройдено {evidence}."

    stats = f"LIVE-картина: xG {xg:.2f}, xGoT {xgot:.2f}, {shots} ударов, {sot} в створ, big chances {big}, в штрафной {inside}."
    score_text = f"Итоговый GOOL {float(score):.0f}/100; коэффициенты в решении не участвуют."

    ext = ""
    try:
        ext = str(getattr(mec, "_external_phrase", lambda _d: "")(delta) or "")
    except Exception:
        ext = ""
    parts = [mode, stats, gate_text, score_text]
    if ext:
        parts.append(ext.rstrip(".") + ".")
    return " ".join(parts)


mec._why = _why
