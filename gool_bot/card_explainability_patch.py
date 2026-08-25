"""Improve GOOL card explainability and source layout without changing signal gates.

- Auxiliary cards explain the exact evidence that passed the strategy gate.
- GOAL/FotMob/365Scores are queried only for an already eligible auxiliary signal
  and shown as independent validation, never as a signal requirement.
- CORE source labels wrap/shrink inside their box instead of overflowing.
"""
from __future__ import annotations

import logging
import re
import textwrap

import candidate_enrichment_patch as ce
import multi_engine_card as mec
import multi_engine_runtime as mer
import signal_card as sc

logger = logging.getLogger("card_explainability")


# ---------- CORE source-box layout ----------

def _fit(draw, text, width, size=32, bold=True):
    text = str(text)
    for z in range(int(size), 8, -1):
        font = sc._font(z, bold)
        if draw.textbbox((0, 0), text, font=font)[2] <= width:
            return font
    return sc._font(9, bold)


def _box(draw, xy, title, value, sub="", accent=sc.TEXT):
    draw.rounded_rectangle(xy, 18, fill=sc.PANEL, outline=sc.LINE, width=2)
    x1, y1, x2, y2 = xy
    draw.text((x1 + 18, y1 + 13), title, font=sc._font(15, True), fill=sc.MUTED)
    draw.text((x1 + 18, y1 + 42), value, font=_fit(draw, value, x2 - x1 - 36, 25, True), fill=accent)
    if sub:
        maxw = x2 - x1 - 36
        # Prefer one compact line, otherwise split into two short lines.
        font = _fit(draw, sub, maxw, 12, False)
        if draw.textbbox((0, 0), str(sub), font=font)[2] <= maxw:
            draw.text((x1 + 18, y2 - 22), str(sub), font=font, fill=sc.MUTED)
        else:
            words = re.split(r"\s*•\s*", str(sub))
            lines = []
            cur = ""
            for word in words:
                trial = word if not cur else cur + " • " + word
                ft = _fit(draw, trial, maxw, 11, False)
                if draw.textbbox((0, 0), trial, font=ft)[2] <= maxw:
                    cur = trial
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            for i, line in enumerate(lines[:2]):
                draw.text((x1 + 18, y2 - 34 + i * 15), line,
                          font=_fit(draw, line, maxw, 10, False), fill=sc.MUTED)


def _source_summary(ctx):
    ext = ctx.get("external_validation") or {}
    names = ["Flashscore"]
    goal = ext.get("goal_api") or {}
    if goal.get("matched") and (goal.get("stats") or goal.get("useful")):
        names.append("GOAL")
    fot = ext.get("fotmob_deep") or ext.get("fotmob") or {}
    ff = fot.get("features") or {}
    if fot.get("matched") and (ff.get("shotmap_n") or ff.get("shot_xg_total") is not None or ff.get("shot_xgot_total") is not None):
        names.append("FotMob")
    s365 = ext.get("scores365_deep") or ext.get("scores365") or {}
    if s365.get("matched") and (s365.get("shots") or s365.get("shot_xg_total") is not None or s365.get("shot_xgot_total") is not None or s365.get("has_stats")):
        names.append("365Scores")
    if ctx.get("history"):
        names.append("Form/H2H")
    return names


sc._fit = _fit
sc._box = _box
sc._source_summary = _source_summary


# ---------- Auxiliary decision audit ----------
_orig_fh = mer.first_half_goal
_orig_sh = mer.second_half_over15
_orig_send_all = mer._send_all


def _fh(minute, d, last_goal_minute=None, timing_bonus=0):
    dec = _orig_fh(minute, d, last_goal_minute, timing_bonus)
    if isinstance(d, dict):
        d["_decision_reason"] = dec.reason
        d["_decision_minute"] = int(minute or 0)
    return dec


def _sh(stats, timing_bonus=0):
    dec = _orig_sh(stats, timing_bonus)
    # For 2H the renderer receives a snapshot later, so the runtime wrapper below
    # will attach the human-readable decision reason when possible.
    return dec


def _useful_external(match):
    try:
        _adj, score, ext = ce._external_adjustment(match)
        return float(score), ext if isinstance(ext, dict) else {}
    except Exception as exc:
        logger.info("Aux external explanation unavailable %s: %s", getattr(match, "event_id", ""), exc)
        return None, {}


def _send_all(match, engine, score, d, odd, result=None):
    if result is None and isinstance(d, dict):
        ext_score, ext = _useful_external(match)
        if ext:
            d["_external_validation"] = ext
        if ext_score is not None:
            d["_external_score"] = ext_score
        if engine == mer.SECOND_HALF_OVER15 and not d.get("_decision_reason"):
            # Reconstruct the same evidence audit used by the strategy.
            xg = float(d.get("xg", 0) or 0); xgot = float(d.get("xgot", 0) or 0)
            shots = float(d.get("shots", 0) or 0); sot = float(d.get("shots_on_target", 0) or 0)
            big = float(d.get("big_chances", 0) or 0); inside = float(d.get("shots_inside_box", 0) or 0)
            touches = float(d.get("touches_box", 0) or 0); corners = float(d.get("corners", 0) or 0)
            evidence = sum((xg >= 1.15, xgot >= .85, shots >= 12, sot >= 4, big >= 2, inside >= 6, touches >= 20, corners >= 4))
            d["_decision_reason"] = f"1H evidence={evidence}/4; xG={xg:.2f}; SOT={sot:.0f}"
    return _orig_send_all(match, engine, score, d, odd, result)


def _evidence_names_first_half(delta):
    checks = [
        (float(delta.get("xg", 0) or 0) >= .18, "xG"),
        (float(delta.get("xgot", 0) or 0) >= .15, "xGoT"),
        (float(delta.get("shots", 0) or 0) >= 2, "удары"),
        (float(delta.get("shots_on_target", 0) or 0) >= 1, "створ"),
        (float(delta.get("big_chances", 0) or 0) >= 1, "big chances"),
        (float(delta.get("touches_box", 0) or 0) >= 5, "касания в штрафной"),
    ]
    return [name for ok, name in checks if ok]


def _external_phrase(delta):
    ext = delta.get("_external_validation") or {}
    reasons = [str(x) for x in (ext.get("reasons") or []) if str(x).strip()]
    useful = []
    goal = ext.get("goal_api") or {}
    if goal.get("matched") and goal.get("stats"):
        useful.append("GOAL")
    fot = ext.get("fotmob_deep") or ext.get("fotmob") or {}
    ff = fot.get("features") or {}
    if fot.get("matched") and (ff.get("shotmap_n") or ff.get("shot_xg_total") is not None):
        useful.append("FotMob")
    s365 = ext.get("scores365_deep") or ext.get("scores365") or {}
    if s365.get("matched") and (s365.get("shots") or s365.get("shot_xg_total") is not None or s365.get("has_stats")):
        useful.append("365Scores")
    if reasons:
        return "Независимая проверка: " + ", ".join(reasons[:2])
    if useful:
        return "Данные дополнительно сверены: " + ", ".join(useful)
    return ""


def _why(engine, score, delta, timing):
    xg = float(delta.get("xg", 0) or 0); xgot = float(delta.get("xgot", 0) or 0)
    shots = int(round(float(delta.get("shots", 0) or 0))); sot = int(round(float(delta.get("shots_on_target", 0) or 0)))
    big = int(round(float(delta.get("big_chances", 0) or 0))); box = int(round(float(delta.get("shots_inside_box", 0) or 0)))
    ext = _external_phrase(delta)
    if engine == "first_half_goal":
        minute = int(delta.get("_decision_minute", 0) or 0)
        names = _evidence_names_first_half(delta)
        needed = 3 if minute >= 22 else 2
        sentence1 = f"С начала наблюдения к {minute}′: xG +{xg:.2f}, {shots} ударов, {sot} в створ"
        if big or box:
            sentence1 += f", big chances {big}, в штрафной {box}"
        sentence1 += "."
        sentence2 = f"Триггеры стратегии: {len(names)}/{needed} — " + (", ".join(names) if names else "нет достаточных LIVE-подтверждений") + "."
        sentence3 = f"GOOL {float(score):.0f}/100 рассчитан из прироста LIVE-метрик; минута только усиливает вес и сама сигнал не создаёт."
        parts = [sentence1, sentence2, sentence3]
        if ext:
            parts.append(ext + ".")
        return " ".join(parts)
    # 2H: explain complete first-half sample rather than just the score.
    reason = str(delta.get("_decision_reason") or "")
    m = re.search(r"evidence=(\d+)(?:/(\d+))?", reason)
    evidence = m.group(1) if m else "—"
    needed = m.group(2) if m and m.group(2) else "4"
    parts = [
        f"Решение принято только в перерыве по всему 1-му тайму: xG {xg:.2f}, {shots} ударов, {sot} в створ, big chances {big}.",
        f"Независимых LIVE-критериев пройдено {evidence}/{needed}; GOOL {float(score):.0f}/100.",
    ]
    if ext:
        parts.append(ext + ".")
    return " ".join(parts)


mer.first_half_goal = _fh
mer.second_half_over15 = _sh
mer._send_all = _send_all
mec._why = _why

logger.info("Card explainability patch active: audited auxiliary reasons + safe source layout")
