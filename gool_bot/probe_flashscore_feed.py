from __future__ import annotations

import asyncio, json, requests
from collections import Counter
from playwright.async_api import async_playwright

URL = "https://www.flashscore.com/football/"
LSAPP_URL = "https://global.ds.lsapp.eu/odds/pq_graphql"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
HEADERS={"User-Agent":UA,"Accept":"application/json, text/plain, */*","Referer":"https://www.flashscore.com/"}

def parse_events(body: str):
    events=[]
    for raw in body.split("~AA÷")[1:]:
        event_id,sep,rest=raw.partition("¬")
        if not sep or len(event_id)!=8: continue
        fields={}
        for token in rest.split("¬"):
            if "÷" in token:
                k,v=token.split("÷",1)
                if k and k not in fields: fields[k]=v
        events.append((event_id,fields))
    return events

def inspect_lsapp(event_id:str):
    params={"_hash":"oce","eventId":event_id,"projectId":"5","geoIpCode":"US","geoIpSubdivisionCode":"USCA"}
    r=requests.get(LSAPP_URL,params=params,headers=HEADERS,timeout=20)
    print("LSAPP",event_id,"status",r.status_code,"bytes",len(r.text))
    try: payload=r.json()
    except Exception: return
    entries=payload.get("data",{}).get("findOddsByEventId",{}).get("odds",[]) or []
    print("LSAPP entries",len(entries))
    for entry in entries[:8]:
        meta={k:v for k,v in entry.items() if k!="odds"}
        print("ENTRY_META",json.dumps(meta,ensure_ascii=False)[:1500])
        for item in (entry.get("odds") or [])[:3]:
            print("ODD_ITEM",json.dumps(item,ensure_ascii=False)[:1800])

async def probe():
    master=None
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=await browser.new_context(user_agent=UA,locale="en-GB",timezone_id="UTC",viewport={"width":1440,"height":1200})
        page=await context.new_page()
        async def on_response(response):
            nonlocal master
            if "f_1_0_0_en_1" in response.url:
                try: master=await response.text()
                except Exception: pass
        page.on("response",on_response)
        await page.goto(URL,wait_until="domcontentloaded",timeout=35000)
        await page.wait_for_timeout(5000)
        if master:
            events=parse_events(master); live=[(eid,f) for eid,f in events if f.get("AB")=="2"]
            print("MASTER LIVE",len(live))
            for eid,f in live[:3]:
                print("MATCH",eid,f.get("AE"),f.get("AF"),f.get("AG"),f.get("AH"),f.get("AC"),f.get("AO"))
                inspect_lsapp(eid)
        await browser.close()

if __name__=="__main__": asyncio.run(probe())
