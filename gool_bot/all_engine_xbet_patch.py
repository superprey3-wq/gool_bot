"""Attach the same 1xBet market snapshot used by CORE to HT HUNTER and LATE RISK cards."""
from __future__ import annotations
import logging
import multi_engine_runtime as mer
from core_result_card_patch import _market_snapshot

logger=logging.getLogger("all_engine_xbet_patch")
_original_send_all=mer._send_all

def _send_all(match,engine,score,d,odd,result=None):
    # Only enrich signal cards. Result cards ignore market payload anyway.
    if result is None:
        payload=dict(d or {})
        try:payload["_xbet"]=_market_snapshot(match)
        except Exception as exc:
            logger.warning("ENGINE_XBET_SNAPSHOT_FAILED %s %s: %s",engine,getattr(match,"event_id",""),exc)
            payload["_xbet"]={}
        d=payload
    return _original_send_all(match,engine,score,d,odd,result)

mer._send_all=_send_all
logger.info("1xBet market snapshot attached to HT HUNTER and LATE RISK cards")
