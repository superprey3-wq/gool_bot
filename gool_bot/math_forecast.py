"""Lightweight pre-match football forecast: Elo strength + Poisson score matrix.

Independent mathematical layer for GOOL BOT. It consumes recent match history
and returns expected goals, 1X2, BTTS and over probabilities.
"""
from __future__ import annotations
import math
from typing import Any


def _mean(xs, default):
    xs = [float(x) for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else float(default)


def _poisson(k, lam):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _elo_expect(home_elo: float, away_elo: float, home_adv: float = 65.0) -> float:
    return 1.0 / (1.0 + 10.0 ** (-((home_elo + home_adv) - away_elo) / 400.0))


def forecast_from_history(home_rows: list[Any], away_rows: list[Any], *, home_elo: float = 1500.0, away_elo: float = 1500.0) -> dict:
    def gfga(row, side):
        if isinstance(row, dict):
            if 'goals_for' in row:
                return float(row.get('goals_for', 0)), float(row.get('goals_against', 0))
            h = float(row.get('home_goals', row.get('fh', 0)) or 0)
            a = float(row.get('away_goals', row.get('fa', 0)) or 0)
        else:
            if hasattr(row, 'goals_for'):
                return float(row.goals_for), float(row.goals_against)
            h = float(getattr(row, 'home_goals', 0) or 0)
            a = float(getattr(row, 'away_goals', 0) or 0)
        return (h, a) if side == 'home' else (a, h)

    h = [gfga(r, 'home') for r in home_rows[-8:]]
    a = [gfga(r, 'away') for r in away_rows[-8:]]
    hgf = _mean([x for x, _ in h], 1.45)
    hga = _mean([y for _, y in h], 1.20)
    agf = _mean([x for x, _ in a], 1.20)
    aga = _mean([y for _, y in a], 1.45)
    elo_h = _elo_expect(home_elo, away_elo)
    elo_a = 1.0 - elo_h

    hx = 0.56 * ((hgf + aga) / 2) + 0.44 * (0.65 + 1.55 * elo_h)
    ax = 0.56 * ((agf + hga) / 2) + 0.44 * (0.55 + 1.45 * elo_a)
    hx = max(0.25, min(3.25, hx))
    ax = max(0.20, min(3.00, ax))

    matrix = {(i, j): _poisson(i, hx) * _poisson(j, ax) for i in range(8) for j in range(8)}
    z = sum(matrix.values()) or 1.0
    matrix = {k: v / z for k, v in matrix.items()}
    p1 = sum(p for (i, j), p in matrix.items() if i > j)
    px = sum(p for (i, j), p in matrix.items() if i == j)
    p2 = sum(p for (i, j), p in matrix.items() if i < j)
    btts = sum(p for (i, j), p in matrix.items() if i > 0 and j > 0)
    overs = {line: sum(p for (i, j), p in matrix.items() if i + j > line) for line in (0.5, 1.5, 2.5, 3.5, 4.5)}
    top = sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        'xg_home': round(hx, 2), 'xg_away': round(ax, 2), 'xg_total': round(hx + ax, 2),
        'home_win': round(p1 * 100, 1), 'draw': round(px * 100, 1), 'away_win': round(p2 * 100, 1),
        'btts': round(btts * 100, 1),
        'overs': {str(k): round(v * 100, 1) for k, v in overs.items()},
        'top_scores': [{'score': f'{i}:{j}', 'p': round(p * 100, 1)} for (i, j), p in top],
        'method': 'Elo+Poisson',
    }
