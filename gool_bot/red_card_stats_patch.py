"""Red-card context from Flashscore event timeline.

Flashscore df_sui_1 encodes incidents separately from match statistics. Public
research of the feed maps IA=3 to a red-card event, so this parser uses the
summary/event stream rather than guessing an SD statistic id.
"""
from __future__ import annotations
import logging,re
import live_engine
logger=logging.getLogger("red_card_stats")


def parse_red_cards(summary_body:str)->tuple[int,int]:
    home=away=0
    for chunk in (summary_body or "").split("~III"):
        if not chunk:continue
        type_m=re.search(r"(?:IA|IAX)(?:÷|¬)(\d+)",chunk)
        if not type_m or int(type_m.group(1))!=3:continue
        # Flashscore variants expose side either explicitly or through score/event
        # side fields. Keep several observed keys and ignore ambiguous incidents.
        side_m=re.search(r"(?:IK|IKX)(?:÷|¬)([^¬~]+)",chunk)
        side=(side_m.group(1).strip().lower() if side_m else "")
        if side in {"1","home","h"}:home+=1
        elif side in {"2","away","a"}:away+=1
        else:
            # Fallback: some feeds use incident participant side flags.
            if re.search(r"(?:IN|INX)(?:÷|¬)1(?:¬|~|$)",chunk):home+=1
            elif re.search(r"(?:IN|INX)(?:÷|¬)2(?:¬|~|$)",chunk):away+=1
    return home,away


def red_cards_for_event(event_id:str)->tuple[int,int]:
    try:
        cards=parse_red_cards(live_engine.fetch_summary(str(event_id)))
        if cards!=(0,0):logger.info("RED_CARD_EVENT %s home=%d away=%d",event_id,*cards)
        return cards
    except Exception:
        logger.exception("RED_CARD_EVENT_FAILED %s",event_id);return (0,0)
