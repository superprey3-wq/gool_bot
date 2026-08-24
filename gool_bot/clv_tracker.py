"""Track price movement for the exact primary market 60s and 120s after entry."""
from __future__ import annotations
import logging,time,statistics
from live_odds import fetch_live_odds
from signal_journal import all_signals,update_signal
logger=logging.getLogger("clv_tracker")


def _same_market_odd(entries,primary):
    try:scope=str(primary["scope"]);line=float(primary["line"])
    except (KeyError,TypeError,ValueError):return None
    prices=[]
    for entry in entries or []:
        if str(entry.get("bettingType") or "")!="OVER_UNDER" or str(entry.get("bettingScope") or "FULL_TIME")!=scope:continue
        for item in entry.get("odds") or []:
            if str(item.get("selection") or "").upper()!="OVER" or item.get("active") is False:continue
            try:
                if abs(float((item.get("handicap") or {}).get("value"))-line)>1e-9:continue
                odd=float(item.get("value"))
            except (TypeError,ValueError,AttributeError):continue
            if odd>1.0:prices.append(odd)
    return float(statistics.median(prices)) if prices else None

def sample(live)->int:
    now=time.time();live_ids={str(m.event_id) for m in live};rows=all_signals();cache={};updates=0
    for row in rows:
        if int(row.get("journal_version",0) or 0)<4:continue
        eid=str(row.get("event_id") or "");primary=row.get("primary")
        if eid not in live_ids or not isinstance(primary,dict):continue
        try:entry_odd=float(primary["odd"]);created=float(row.get("created_ts",0) or 0)
        except (KeyError,TypeError,ValueError):continue
        age=now-created
        targets=[]
        if age>=60 and row.get("clv_60_odd") is None:targets.append(60)
        if age>=120 and row.get("clv_120_odd") is None:targets.append(120)
        if not targets:continue
        if eid not in cache:
            try:cache[eid]=fetch_live_odds(eid)
            except Exception:cache[eid]=[]
        current=_same_market_odd(cache[eid],primary)
        if current is None:continue
        fields={}
        implied_entry=100.0/entry_odd;implied_now=100.0/current
        for sec in targets:
            fields[f"clv_{sec}_odd"]=round(current,6)
            fields[f"clv_{sec}_implied_pp"]=round(implied_now-implied_entry,2)
            fields[f"clv_{sec}_ts"]=int(now)
        if update_signal(str(row.get("dedupe_key") or ""),**fields):updates+=1
    if updates:logger.info("CLV_UPDATED rows=%d",updates)
    return updates
