"""Extract red-card counts from Flashscore stats by label without hard-coding an unstable stat id."""
from __future__ import annotations
import re,logging
import live_engine
import unified_bot
logger=logging.getLogger("red_card_stats")
_original=live_engine.parse_stats
_LABEL_RE=re.compile(r"red\s*cards?|красн\w*\s+карточ",re.I)

def parse_stats(body):
    out=_original(body)
    for chunk in (body or "").split("~"):
        if not _LABEL_RE.search(chunk):continue
        m=re.search(r"SH(?:÷|¬)([^¬~]+).*?SI(?:÷|¬)([^¬~]+)",chunk)
        if not m:continue
        try:out["red_cards"]=(float(m.group(1)),float(m.group(2)))
        except (TypeError,ValueError):continue
        logger.info("RED_CARD_STATS detected home=%s away=%s",out["red_cards"][0],out["red_cards"][1])
        break
    return out

live_engine.parse_stats=parse_stats
unified_bot.parse_stats=parse_stats
