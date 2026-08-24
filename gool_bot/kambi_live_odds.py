"""Kambi/BetRivers LIVE football totals fallback.

Discovers Kambi football events automatically, fuzzy-matches Flashscore team
names, then fetches the event bet-offer payload and returns active STANDARD
full-match/period goal totals only. Quarter Asian lines and team totals are
explicitly excluded because GOOL works only with normal .0/.5 totals.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any

try:
    from curl_cffi import requests as http_requests
    _HAS_CURL_CFFI = True
except ImportError:
    import requests as http_requests
    _HAS_CURL_CFFI = False

logger = logging.getLogger("kambi_live_odds")
OPERATOR = "rsiusnj"
LIST_URL = (
    "https://eu-offering-api.kambicdn.com/offering/v2018/"
    f"{OPERATOR}/listView/football/all/all/all/matches.json?lang=en_US&market=US"
)
EVENT_URL = (
    "https://eu-offering-api.kambicdn.com/offering/v2018/"
    f"{OPERATOR}/betoffer/event/{{event_id}}.json?lang=en_US&market=US&includeParticipants=true"
)
_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])
_CACHE_SECONDS = 25


def _get(url: str, timeout: int = 15):
    kwargs = {"timeout": timeout, "headers": {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}}
    if _HAS_CURL_CFFI:
        kwargs["impersonate"] = "chrome120"
    return http_requests.get(url, **kwargs)


def _norm(value: str) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|afc|cf|sc|fk|sv|ac|as|eng|ita|ger|den|hun|esp|gre)\b", " ", s)
    s = re.sub(r"\b(women|woman|w)\b", " women ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b: return 0.0
    if a == b: return 1.0
    if a in b or b in a: return 0.92
    return SequenceMatcher(None, a, b).ratio()


def _is_live(event: dict[str, Any]) -> bool:
    state = str(event.get("state") or "").upper()
    return state not in {"", "NOT_STARTED", "ENDED", "FINISHED", "CANCELLED"}


def _live_events() -> list[dict[str, Any]]:
    global _CACHE
    now = time.time()
    if now - _CACHE[0] < _CACHE_SECONDS and _CACHE[1]: return _CACHE[1]
    try:
        r = _get(LIST_URL, timeout=15); r.raise_for_status(); wrappers = r.json().get("events") or []
    except Exception as exc:
        logger.info("KAMBI_LIST_FAILED: %s", exc); return _CACHE[1] if _CACHE[1] else []
    events=[]
    for wrapper in wrappers:
        event=wrapper.get("event") or wrapper
        if event.get("homeName") and event.get("awayName") and _is_live(event): events.append(event)
    _CACHE=(now,events); return events


def _find_event(home: str, away: str) -> dict[str, Any] | None:
    best=None
    for event in _live_events():
        h,a=str(event.get("homeName") or ""),str(event.get("awayName") or "")
        score=max((_sim(home,h)+_sim(away,a))/2,(_sim(home,a)+_sim(away,h))/2)
        if best is None or score>best[0]: best=(score,event)
    return best[1] if best and best[0]>=0.72 else None


def _scope_from_offer(criterion: str, type_name: str) -> str:
    text=f"{criterion} {type_name}".lower()
    if "1st half" in text or "first half" in text or "1h" in text:return "FIRST_HALF"
    if "2nd half" in text or "second half" in text or "2h" in text:return "SECOND_HALF"
    return "FULL_TIME"


def _standard_line(line: float) -> bool:
    # GOOL accepts integer/half totals only: 1.5, 2.0, 2.5, 3.0, ...
    return abs(float(line)*2-round(float(line)*2)) < 1e-9


def get_live_goal_totals(home: str, away: str) -> list[dict[str, Any]]:
    event=_find_event(home,away)
    if not event:return []
    event_id=event.get("id")
    try:
        r=_get(EVENT_URL.format(event_id=event_id),timeout=15); r.raise_for_status(); data=r.json()
    except Exception as exc:
        logger.info("KAMBI_EVENT_FAILED %s %s — %s: %s",home,away,event_id,exc); return []
    rows=[]
    for offer in data.get("betOffers") or []:
        type_name=str((offer.get("betOfferType") or {}).get("name") or "")
        criterion=str((offer.get("criterion") or {}).get("label") or "")
        key=f"{type_name} {criterion}".lower()
        # Standard match/period total only. No Asian/quarter, team, corners/cards/shots.
        if not any(x in key for x in ("over/under","total goals")):continue
        if "asian" in key or " by " in key or any(x in key for x in ("corner","card","shot","booking")):continue
        scope=_scope_from_offer(criterion,type_name)
        for outcome in offer.get("outcomes") or []:
            if outcome.get("status")!="OPEN":continue
            label=str(outcome.get("label") or "").lower(); otype=str(outcome.get("type") or "")
            if "over" not in label and otype!="OT_OVER":continue
            try:
                odd=float(outcome.get("odds"))/1000.0
                raw=outcome.get("line"); line=float(raw)/1000.0 if raw is not None else None
            except (TypeError,ValueError):continue
            if line is None or odd<=1.0 or not _standard_line(line):continue
            rows.append({"scope":scope,"line":line,"odd":odd,"source":"Kambi/BetRivers","bookmakers":1,"event_id":str(event_id)})
    logger.info("KAMBI_MATCHED %s — %s -> %s rows=%d",home,away,event_id,len(rows)); return rows
