"""Probe hockey LIVE market feeds without touching football runtime."""
from __future__ import annotations
import json
import requests

UA={"User-Agent":"Mozilla/5.0","Accept":"application/json","Cache-Control":"no-cache"}
BOVADA_CANDIDATES=(
    "https://www.bovada.lv/services/sports/event/v2/events/A/description/hockey?lang=en&liveOnly=true",
    "https://www.bovada.lv/services/sports/event/v2/events/A/description/ice-hockey?lang=en&liveOnly=true",
)

def walk_events(node,out):
    if isinstance(node,dict):
        if isinstance(node.get("displayGroups"),list) and node.get("description"):
            out.append(node)
        for v in node.values(): walk_events(v,out)
    elif isinstance(node,list):
        for v in node: walk_events(v,out)

def over_under_rows(event):
    rows=[]
    for group in event.get("displayGroups") or []:
        gd=str(group.get("description") or "")
        for market in group.get("markets") or []:
            md=str(market.get("description") or "")
            low=md.lower()
            if not any(k in low for k in ("total","over/under","goals")):
                continue
            outs=[]
            for o in market.get("outcomes") or []:
                p=o.get("price") or {}
                outs.append({
                    "sel":o.get("description"),
                    "handicap":p.get("handicap"),
                    "decimal":p.get("decimal"),
                    "status":o.get("status"),
                })
            rows.append({"group":gd,"market":md,"outcomes":outs})
    return rows

def main():
    for url in BOVADA_CANDIDATES:
        label=url.split("/description/",1)[-1].split("?",1)[0]
        try:
            r=requests.get(url,headers=UA,timeout=20)
            print(f"BOVADA {label}: HTTP={r.status_code} bytes={len(r.content)} type={r.headers.get('content-type')}")
            if not r.ok: continue
            payload=r.json(); events=[]; walk_events(payload,events)
            print(f"BOVADA {label}: events={len(events)}")
            for e in events[:20]:
                rows=over_under_rows(e)
                print(f"EVENT {e.get('id')} | {e.get('description')} | groups={len(e.get('displayGroups') or [])} totals={len(rows)}")
                for row in rows[:12]:
                    print("  MARKET "+json.dumps(row,ensure_ascii=False,separators=(',',':')))
            if events:
                break
        except Exception as exc:
            print(f"BOVADA {label}: ERROR {type(exc).__name__}: {exc}")

if __name__=="__main__":
    main()
