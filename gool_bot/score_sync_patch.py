"""Synchronize Flashscore live-card state with event summary before analysis.

Important: summary scores are authoritative snapshots. Never keep the maximum
score seen in earlier chunks: VAR/cancelled goals can make a score go backwards.
"""
from __future__ import annotations
import logging,re
import unified_bot
from live_engine import fetch_summary
logger=logging.getLogger("score_sync_patch")
_orig_discover=unified_bot.discover_live_matches
_orig_send_signal=unified_bot.telegram_send_signal

def _summary_state(body:str):
    if not body:return None,None
    score=None;last_goal_minute=None
    # Keep the LAST explicit score in the summary stream. Using max() here is
    # wrong because an annulled VAR goal legitimately changes 1:1 back to 1:0.
    for chunk in body.split("~III"):
        hm=re.search(r"INX(?:÷|¬)(\d+)",chunk);am=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
        if not hm and not am:continue
        prev=score or (0,0)
        new=(int(hm.group(1)) if hm else prev[0],int(am.group(1)) if am else prev[1])
        if sum(new)>sum(prev):
            mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:\+(\d{1,2}))?",chunk)
            if mm:last_goal_minute=int(mm.group(1))+int(mm.group(2) or 0)
        elif sum(new)<sum(prev):
            # Score rollback = cancelled/corrected goal. Do not keep that goal
            # as confirmed evidence for SIGNAL WON or recent-goal blocking.
            last_goal_minute=None
            logger.warning("SUMMARY_GOAL_ROLLBACK detected %s -> %s",prev,new)
        score=new
    return score,last_goal_minute

async def _discover_synced():
    matches=await _orig_discover()
    for match in matches:
        try:body=fetch_summary(match.event_id);score,last_goal_minute=_summary_state(body)
        except Exception as exc:logger.info("SUMMARY_STATE_SYNC_FAILED %s: %s",match.event_id,exc);continue
        match.summary_last_goal_minute=last_goal_minute;match.summary_goal_ahead=False;match.summary_score=score
        if score:
            sh,sa=score;live=(int(match.home_score),int(match.away_score))
            # Summary may move both forward (new goal) and backward (VAR). For
            # analysis use its current authoritative score, never a historical max.
            if (sh,sa)!=live:
                old=f"{live[0]}:{live[1]}";match.home_score,match.away_score=sh,sa
                match.summary_goal_ahead=(sh+sa)>(live[0]+live[1])
                tag="STALE_SCORE_FIXED" if match.summary_goal_ahead else "SCORE_ROLLBACK_FIXED"
                logger.warning("%s %s %s — %s | %s -> %d:%d",tag,match.event_id,match.home,match.away,old,sh,sa)
        if last_goal_minute is not None and int(match.minute)<last_goal_minute:match.minute=last_goal_minute
        if bool(getattr(match,"is_halftime",False)) and (int(match.minute)>45 or (last_goal_minute is not None and last_goal_minute>45)):match.is_halftime=False
        if last_goal_minute is None:match.minutes_since_confirmed_goal=None;match.recent_confirmed_goal=False
        else:
            since=max(0,int(match.minute)-int(last_goal_minute));match.minutes_since_confirmed_goal=since;match.recent_confirmed_goal=since<3
    return matches

def _send_synced(match,pressure,recs,text):
    recent=bool(getattr(match,"recent_confirmed_goal",False));goal_success="СИГНАЛ ЗАШЁЛ" in str(text) or "ГОЛ — СИГНАЛ СРАБОТАЛ" in str(text) or "ГОЛ ЗАФИКСИРОВАН" in str(text)
    if recent and not goal_success:
        logger.warning("RECENT_GOAL_SIGNAL_BLOCKED %s %s — %s",getattr(match,"event_id","?"),getattr(match,"home","?"),getattr(match,"away","?"));return False
    return _orig_send_signal(match,pressure,recs,text)
unified_bot.discover_live_matches=_discover_synced
unified_bot.telegram_send_signal=_send_synced
