"""Lightweight LIVE state helpers.

The old version fetched a Flashscore summary for every LIVE match during discovery.
With 100-200 matches that turned one browser scan into hundreds of sequential HTTP
requests and made match minutes stale by the time analysis reached them.

Discovery is now fast: the Flashscore LIVE list is the authoritative current minute/score
for the cycle. Summary is fetched only for shortlisted candidates and active goal watches.
"""
from __future__ import annotations
import logging,re
import unified_bot

logger=logging.getLogger("score_sync_patch")
_orig_discover=unified_bot.discover_live_matches
_orig_send_signal=unified_bot.telegram_send_signal
_REUSE_ONCE=None


def _summary_state(body:str):
    """Return (current score, last confirmed goal minute) from one summary payload."""
    if not body:return None,None
    score=None;last_goal_minute=None
    for chunk in body.split("~III"):
        hm=re.search(r"INX(?:÷|¬)(\d+)",chunk);am=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
        if not hm and not am:continue
        prev=score or (0,0)
        new=(int(hm.group(1)) if hm else prev[0],int(am.group(1)) if am else prev[1])
        if sum(new)>sum(prev):
            mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:\+(\d{1,2}))?",chunk)
            if mm:last_goal_minute=int(mm.group(1))+int(mm.group(2) or 0)
        elif sum(new)<sum(prev):
            last_goal_minute=None
            logger.warning("SUMMARY_GOAL_ROLLBACK detected %s -> %s",prev,new)
        score=new
    return score,last_goal_minute


def reuse_once(matches):
    """Feed the already-discovered list into the next CORE scan exactly once."""
    global _REUSE_ONCE
    _REUSE_ONCE=list(matches or [])


async def _discover_fast():
    global _REUSE_ONCE
    if _REUSE_ONCE is not None:
        matches=_REUSE_ONCE
        _REUSE_ONCE=None
        logger.info("LIVE_REUSE_ONCE matches=%d",len(matches))
        return matches
    matches=await _orig_discover()
    for match in matches:
        # Keep stable attributes for downstream code without issuing N summary requests.
        match.summary_last_goal_minute=None
        match.summary_goal_ahead=False
        match.summary_score=(int(getattr(match,"home_score",0) or 0),int(getattr(match,"away_score",0) or 0))
        match.minutes_since_confirmed_goal=None
        match.recent_confirmed_goal=False
    return matches


def _send_synced(match,pressure,recs,text):
    recent=bool(getattr(match,"recent_confirmed_goal",False))
    goal_success="СИГНАЛ ЗАШЁЛ" in str(text) or "ГОЛ — СИГНАЛ СРАБОТАЛ" in str(text) or "ГОЛ ЗАФИКСИРОВАН" in str(text)
    if recent and not goal_success:
        logger.warning("RECENT_GOAL_SIGNAL_BLOCKED %s %s — %s",getattr(match,"event_id","?"),getattr(match,"home","?"),getattr(match,"away","?"))
        return False
    return _orig_send_signal(match,pressure,recs,text)

unified_bot.discover_live_matches=_discover_fast
unified_bot.telegram_send_signal=_send_synced
