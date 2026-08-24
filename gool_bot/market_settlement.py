"""Auditable settlement helpers for GOOL LIVE primary markets."""
from __future__ import annotations
from math import floor
from typing import Any


def parse_score(value: Any) -> tuple[int, int]:
    try:
        a, b = str(value or "0:0").split(":", 1)
        return int(a), int(b)
    except Exception:
        return 0, 0


def _over_legs(line: float) -> list[float]:
    line = round(float(line), 2)
    whole = floor(line)
    frac = round(line - whole, 2)
    if frac == 0.25:
        return [float(whole), whole + 0.5]
    if frac == 0.75:
        return [whole + 0.5, float(whole + 1)]
    return [line]


def over_pnl_units(line: float, odd: float, total_goals: int) -> float:
    """Return flat-stake P/L for an Asian/standard Total Over market."""
    odd = float(odd)
    if odd <= 1.0:
        raise ValueError("odd must be > 1.0")
    legs = _over_legs(float(line))
    pnl = 0.0
    stake = 1.0 / len(legs)
    for leg in legs:
        if total_goals > leg:
            pnl += stake * (odd - 1.0)
        elif abs(total_goals - leg) < 1e-9:
            pnl += 0.0
        else:
            pnl -= stake
    return round(pnl, 6)


def settle_primary(primary: dict[str, Any] | None, final_score: Any) -> dict[str, Any] | None:
    if not isinstance(primary, dict):
        return None
    market = str(primary.get("market") or "TOTAL_OVER").upper()
    if market not in {"TOTAL_OVER", "OVER_UNDER", "OVER"}:
        return None
    try:
        line = float(primary["line"])
        odd = float(primary["odd"])
    except (KeyError, TypeError, ValueError):
        return None
    h, a = parse_score(final_score)
    pnl = over_pnl_units(line, odd, h + a)
    if pnl > 1e-9:
        result = "+"
    elif pnl < -1e-9:
        result = "-"
    else:
        result = "push"
    return {
        "result": result,
        "pnl_units": pnl,
        "settled_total_goals": h + a,
        "settled_line": line,
        "settled_odd": odd,
    }


def fully_won_now(primary: dict[str, Any] | None, current_score: Any) -> bool:
    """True only when every Asian leg is already irreversibly won."""
    if not isinstance(primary, dict):
        return False
    try:
        line = float(primary["line"])
    except (KeyError, TypeError, ValueError):
        return False
    h, a = parse_score(current_score)
    total = h + a
    return all(total > leg for leg in _over_legs(line))
