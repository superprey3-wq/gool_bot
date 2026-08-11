from __future__ import annotations

import asyncio
from collections import Counter
from playwright.async_api import async_playwright

URL = "https://www.flashscore.com/football/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"


def parse_events(body: str):
    events = []
    for raw in body.split("~AA÷")[1:]:
        event_id, sep, rest = raw.partition("¬")
        if not sep or len(event_id) != 8:
            continue
        fields = {}
        for token in rest.split("¬"):
            if "÷" in token:
                k, v = token.split("÷", 1)
                if k and k not in fields:
                    fields[k] = v
        events.append((event_id, fields))
    return events


async def probe(locale: str):
    master = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent=UA, locale=locale, timezone_id="UTC", viewport={"width":1440,"height":1200})
        page = await context.new_page()

        async def on_response(response):
            nonlocal master
            if "f_1_0_0_en_1" in response.url:
                try: master = await response.text()
                except Exception: pass

        page.on("response", on_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(5000)
        for _ in range(14):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(450)
        live_rows = page.locator("div[id*='g_1_'].event__match--live")
        print(f"LOCALE {locale}: DOM live={await live_rows.count()}")

        if master:
            events = parse_events(master)
            ab = Counter(f.get("AB", "") for _, f in events)
            print(f"MASTER {locale}: events={len(events)} AB={dict(ab)}")
            live=[(eid,f) for eid,f in events if f.get('AB')=='2']
            print(f"MASTER LIVE {locale}: {len(live)}")
            for eid,f in live[:12]:
                keep={k:v for k,v in f.items() if k in {'AB','AC','AD','ADE','AE','AF','AG','AH','AO','AX','AW','BX','BC','BD','AT','AU','CR','RW'}}
                print(f"LIVE_FIELDS {eid} {f.get('AE')}—{f.get('AF')} {keep}")
        await browser.close()


async def main():
    await probe("en-GB")

if __name__ == "__main__":
    asyncio.run(main())
