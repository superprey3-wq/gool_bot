"""Run the validated Flashscore/LSApp collector as a LIVE TOTAL O/U node.

PROGRUZ only needs real live matches and over/under totals. Other markets are
left out of the collector path so requests and state stay small. BEST BET remains
independent on the main branch.
"""
from __future__ import annotations
import os
import browser_market_node as node

# Bounded live scan. We can price up to 24 concurrent live matches while keeping
# memory and request volume low on MonkeyBytes.
node.MAX_EVENTS=max(20,min(100,int(os.getenv("GOOL_MARKET_MAX_EVENTS","60"))))
node.MAX_ODDS_EVENTS=max(4,min(24,int(os.getenv("GOOL_MARKET_ODDS_EVENTS","24"))))
node.MAX_RECORDS=max(200,min(2200,int(os.getenv("GOOL_MARKET_MAX_RECORDS","1200"))))
node.MAX_RECORDS_PER_EVENT=max(40,min(220,int(os.getenv("GOOL_MARKET_PER_EVENT","140"))))

# PROGRUZ market universe: totals only. Keep FT/1H/2H totals because all are
# useful live decisions, but remove 1X2/AH/BTTS/DC/DNB from this worker.
node.ALLOWED_MARKETS={"OVER_UNDER"}
node.MARKET_NAMES={"OVER_UNDER":"TOTAL"}
node.MAX_ODD_BY_MARKET={"OVER_UNDER":12.0}

# Flashscore feed AB == "2" is the real LIVE flag. The validated v6 collector
# previously kept a broad event list and only tried to prioritise live-looking
# rows later; replace that with an exact live pool before any LSApp request.
def _live_events(rows):
    events=[]
    for r in rows:
        if str(r.get("AB") or "") != "2":
            continue
        eid=r.get("AA")
        if not eid:
            continue
        events.append({
            "source":"flashscore",
            "event_id":str(eid),
            "home":r.get("AE") or r.get("CX") or "",
            "away":r.get("AF") or r.get("CX_2") or "",
            "home_score":r.get("AG"),
            "away_score":r.get("AH"),
            "status":r.get("AC") or r.get("BC") or "LIVE",
            "start_ts":r.get("AD"),
            "live_flag":"2",
            "minute":r.get("BA"),
            "raw":{k:r[k] for k in list(r)[:32]},
        })
        if len(events)>=node.MAX_EVENTS:
            break
    return events

node._flash_events=_live_events

if __name__=="__main__":
    node.LOG.info(
        "GOOL_MARKET_LIVE mode=LIVE_TOTAL_OU live_only=AB2 odds_events=%d records=%d per_event=%d",
        node.MAX_ODDS_EVENTS,node.MAX_RECORDS,node.MAX_RECORDS_PER_EVENT,
    )
    node.main()
