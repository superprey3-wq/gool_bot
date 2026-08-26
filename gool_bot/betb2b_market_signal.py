"""BetB2B/1xBet market context for GOOL cards.

Read-only helper: market movement is supplementary information only and MUST NOT
create, block or change a GOOL signal probability. 1xBet/Melbet are treated as
one BETB2B source cluster.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class MarketPoint:
    ts: float
    odds: float
    line: Optional[float] = None
    source: str = "BETB2B"


@dataclass(frozen=True)
class MarketSignal:
    dot: str
    delta_pp: float
    fast: bool
    direction: int  # +1 supports target event, 0 neutral, -1 opposes


def implied_probability(odds: float) -> Optional[float]:
    try:
        x = float(odds)
    except (TypeError, ValueError):
        return None
    return 1.0 / x if x > 1.0 else None


def classify_market(points: Iterable[MarketPoint], *, target_is_selection: bool = True) -> MarketSignal:
    """Classify movement of the selected outcome.

    Temporary display thresholds until GOOL has enough history:
      abs(delta) < 1.5 pp -> neutral/yellow
      >= 1.5 pp in target direction -> green
      >= 1.5 pp against target -> red
    Lightning marks >=4 pp within five minutes.
    """
    pts = sorted((p for p in points if implied_probability(p.odds) is not None), key=lambda p: p.ts)
    if len(pts) < 2:
        return MarketSignal("🟡", 0.0, False, 0)
    a, b = pts[0], pts[-1]
    pa, pb = implied_probability(a.odds), implied_probability(b.odds)
    delta = (pb - pa) * 100.0
    if not target_is_selection:
        delta = -delta
    # A movement of the offered main line in the target direction reinforces price movement.
    if a.line is not None and b.line is not None and a.line != b.line:
        line_move = b.line - a.line
        if target_is_selection:
            delta += max(-2.0, min(2.0, line_move * 2.0))
    if abs(delta) < 1.5:
        direction, dot = 0, "🟡"
    elif delta > 0:
        direction, dot = 1, "🟢"
    else:
        direction, dot = -1, "🔴"
    fast = abs(delta) >= 4.0 and (b.ts - a.ts) <= 300
    return MarketSignal(dot, round(delta, 2), fast, direction)


def card_market_dot(signal: Optional[MarketSignal]) -> str:
    """Only the private dot is rendered on Telegram cards; no market text."""
    if signal is None:
        return "🟡"
    return signal.dot + ("⚡" if signal.fast else "")


def source_cluster(source: str) -> str:
    """Do not double-count 1xBet and Melbet as independent confirmations."""
    s = (source or "").lower()
    if "1xbet" in s or "melbet" in s or "betb2b" in s:
        return "BETB2B"
    return (source or "UNKNOWN").upper()
