"""Reset sharp-move baselines after score/state changes.

A large odds move immediately after a goal is normal repricing, not evidence of
new money flow.  This patch observes verified LIVE score updates and suppresses
TOP-load alerts for a short stabilization window after a score change.
"""
from __future__ import annotations
import logging,os,time
import market_test_signal as mts
log=logging.getLogger("market_event_reset")
RESET_SECONDS=int(os.getenv("MARKET_EVENT_RESET_SECONDS","120"));_SCORES={};_RESET={}
_orig_update=mts.update_live_context;_orig_sharp=mts._sharp
def _eid_obj(x):return str(getattr(x,"event_id","") or "")
def _eid_sig(s):return str(s.get("fs_id") or s.get("event_id") or "")
def update_live_context(live):
 now=time.time()
 for m in live or []:
  eid=_eid_obj(m)
  if not eid:continue
  score=f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}";prev=_SCORES.get(eid)
  if prev is not None and prev!=score:
   _RESET[eid]=now+RESET_SECONDS;log.info("MARKET_EVENT_RESET event=%s score=%s->%s hold=%ss",eid,prev,score,RESET_SECONDS)
  _SCORES[eid]=score
 for eid in list(_RESET):
  if _RESET[eid]<=now:_RESET.pop(eid,None)
 return _orig_update(live)
def sharp(s):
 eid=_eid_sig(s);until=_RESET.get(eid,0)
 if until>time.time():
  log.info("TOPLOAD_REJECT reason=post_event_reset event=%s remaining=%ds",eid,int(until-time.time()));return False
 return _orig_sharp(s)
mts.update_live_context=update_live_context;mts._sharp=sharp
log.info("MARKET_EVENT_RESET enabled seconds=%d",RESET_SECONDS)
