"""Hard 5-minute CORE cooldown after a detected score change.

Independent from Flashscore goal-timeline lag. The module is imported by the production
root main.py and patches live_candidate_patch._evaluate in-place.
"""
from __future__ import annotations
import time
import live_candidate_patch as lc

_orig_evaluate = lc._evaluate
_seen = {}
REAL_COOLDOWN_SECONDS = 5 * 60
MATCH_COOLDOWN_MINUTES = 5


def _evaluate(m, s, p, goals, market):
    eid = str(getattr(m, "event_id", "") or "")
    minute = int(getattr(m, "minute", 0) or 0)
    score = (int(getattr(m, "home_score", 0) or 0), int(getattr(m, "away_score", 0) or 0))
    now = time.time()
    row = _seen.get(eid)
    if row is None:
        row = {"score": score, "goal_ts": 0.0, "goal_minute": None}
        _seen[eid] = row
    elif tuple(row.get("score", score)) != score:
        row.update(score=score, goal_ts=now, goal_minute=minute)

    result = _orig_evaluate(m, s, p, goals, market)
    goal_ts = float(row.get("goal_ts", 0) or 0)
    goal_minute = row.get("goal_minute")
    in_real_cooldown = goal_ts > 0 and (now - goal_ts) < REAL_COOLDOWN_SECONDS
    in_match_cooldown = goal_minute is not None and (minute - int(goal_minute)) < MATCH_COOLDOWN_MINUTES
    if not (in_real_cooldown or in_match_cooldown):
        return result

    qualifies, route, master, sc, hz, mkt = result
    return False, "HARD_POST_GOAL_COOLDOWN", master, sc, hz, mkt


lc._evaluate = _evaluate
