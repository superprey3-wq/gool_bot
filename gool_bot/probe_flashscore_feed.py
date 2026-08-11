from __future__ import annotations

import asyncio
import re
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
            if "f_1_0_0_en_1" not in response.url:
                return
            try:
                master = await response.text()
            except Exception:
                pass

        page.on("response", on_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(5000)
        for _ in range(14):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(450)
        await page.wait_for_timeout(1000)

        all_rows = page.locator("div[id*='g_1_']")
        live_rows = page.locator("div[id*='g_1_'].event__match--live")
        print(f"LOCALE {locale}: DOM all={await all_rows.count()} live={await live_rows.count()}")

        if master:
            events = parse_events(master)
            ac = Counter(fields.get("AC", "") for _, fields in events)
            ab = Counter(fields.get("AB", "") for _, fields in events)
            print(f"MASTER {locale}: events={len(events)} AC={dict(ac)} AB={dict(ab)} bytes={len(master)}")
            for status in sorted(ac):
                sample=[]
                for eid, f in events:
                    if f.get("AC", "") != status:
                        continue
                    sample.append(f"{eid}:{f.get('AE','?')}—{f.get('AF','?')} score={f.get('AG','?')}:{f.get('AH','?')} AD={f.get('AD','?')} AB={f.get('AB','?')}")
                    if len(sample)>=8: break
                print(f"AC={status!r} SAMPLE: {' || '.join(sample)}")
        await browser.close()


async def main():
    for locale in ("en-GB", "ru-RU"):
        try:
            await probe(locale)
        except Exception as exc:
            print(f"ERROR {locale}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
