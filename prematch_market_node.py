"""GOOL prematch collector: today + tomorrow fixtures and LSApp opening/current odds.
Data-only. Reuses the validated lightweight Flashscore/LSApp parser from browser_market_node.
"""
from __future__ import annotations
import json, logging, os, time
from pathlib import Path
from datetime import datetime, timezone
import browser_market_node as live

LOG=logging.getLogger("gool.prematch")
OUT=Path(os.getenv("GOOL_PREMATCH_STATE","prematch_market_state.json"))
POLL=max(180,int(os.getenv("GOOL_PREMATCH_POLL_SECONDS","300")))
MAX_FIXTURES=max(40,min(300,int(os.getenv("GOOL_PREMATCH_MAX_FIXTURES","220"))))
MAX_ODDS=max(20,min(160,int(os.getenv("GOOL_PREMATCH_ODDS_EVENTS","100"))))
FEED_TMPL="https://local-global.flashscore.ninja/2/x/feed/f_1_{day}_3_en_1"

def get_feed(lib, day):
    r=live._get(lib, FEED_TMPL.format(day=day), live.FLASH_HEADERS)
    rows=live._decode_flash_feed(r.get("body") or "") if r.get("ok") else []
    events=live._flash_events(rows)
    return r, events

def unique_events(groups):
    out={}
    for label, events in groups:
        for e in events:
            eid=str(e.get("event_id") or "")
            if not eid: continue
            x=dict(e); x["schedule_day"]=label
            out[eid]=x
    return list(out.values())[:MAX_FIXTURES]

def fetch_odds(lib, events):
    records=[]; priced=set(); ok=0
    ts=datetime.now(timezone.utc).isoformat()
    for e in events[:MAX_ODDS]:
        r=live._get(lib, live._lsapp_url(e["event_id"]), live.LSAPP_HEADERS)
        if not r.get("ok"): continue
        ok+=1
        try: payload=json.loads(r.get("body") or "{}")
        except Exception: continue
        rows,_,_=live._normalize_odds(e,payload,ts)
        if rows:
            priced.add(str(e["event_id"])); records.extend(rows)
    return records,priced,ok

def atomic_write(payload):
    tmp=OUT.with_suffix(OUT.suffix+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8"); tmp.replace(OUT)

def cycle(lib):
    r0,e0=get_feed(lib,0); r1,e1=get_feed(lib,1)
    events=unique_events((("today",e0),("tomorrow",e1)))
    records,priced,ok=fetch_odds(lib,events)
    payload={"version":1,"updated_at":datetime.now(timezone.utc).isoformat(),"today":len(e0),"tomorrow":len(e1),"fixtures":events,"priced_events":len(priced),"odds_records":records}
    atomic_write(payload)
    books=len({r.get("bookmaker") for r in records if r.get("bookmaker")})
    markets=sorted({r.get("market") for r in records if r.get("market")})
    LOG.info("PREMATCH_V1 today=%s tomorrow=%s fixtures=%s lsapp=%s/%s priced=%s records=%s books=%s markets=%s",len(e0),len(e1),len(events),ok,min(len(events),MAX_ODDS),len(priced),len(records),books,",".join(markets) or "none")

def main():
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    name,lib=live._client(); LOG.info("GOOL_PREMATCH_NODE v1 starting client=%s poll=%ss days=today+tomorrow",name,POLL)
    while True:
        try: cycle(lib)
        except Exception: LOG.exception("PREMATCH cycle failed")
        time.sleep(POLL)
if __name__=="__main__": main()
