"""One-shot live Flashscore stats diagnostic. No Telegram sends."""
from __future__ import annotations

import asyncio
import re
import requests
from playwright.async_api import async_playwright

FSIGN = "SW9D1eZo"
HOSTS = ["global", "2", "46"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
STAT_MAP = {
    "432": "expected_goals",
    "499": "xg_on_target",
    "12": "ball_possession",
    "34": "total_shots",
    "13": "shots_on_target",
    "14": "shots_off_target",
    "158": "blocked_shots",
    "461": "shots_inside_box",
    "463": "shots_outside_box",
    "459": "big_chances",
    "16": "corner_kicks",
    "471": "touches_in_opposition_box",
    "23": "yellow_cards",
}


def fetch_stats(mid: str):
    headers = {
        "User-Agent": UA,
        "x-fsign": FSIGN,
        "Origin": "https://www.flashscore.com",
        "Referer": "https://www.flashscore.com/",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for host in HOSTS:
        url = f"https://{host}.flashscore.ninja/2/x/feed/df_st_1_{mid}"
        try:
            r = requests.get(url, headers=headers, timeout=15)
            print(f"STAT host={host} status={r.status_code} bytes={len(r.text)}")
            if r.status_code == 200 and r.text.strip() and not r.text.lstrip().lower().startswith("<"):
                return r.text
        except Exception as e:
            print(f"STAT host={host} error={e}")
    return ""


def raw_stat_fragments(body: str):
    for sid, name in STAT_MAP.items():
        pos = body.find(f"SD¬{sid}")
        if pos >= 0:
            print(f"RAW_{name}: {body[max(0,pos-90):pos+210]}")


async def discover_live_rows():
    found = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(user_agent=UA, locale="en-GB", timezone_id="UTC", viewport={"width":1440,"height":1200})
        page = await context.new_page()
        await page.goto("https://www.flashscore.com/football/", wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(4500)
        # Click LIVE filter when available so candidates are true live events.
        clicked = False
        for selector in ["text=LIVE", "[data-testid='wcl-tab']:has-text('LIVE')", "button:has-text('LIVE')"]:
            try:
                loc = page.locator(selector)
                if await loc.count():
                    await loc.first.click(timeout=3000)
                    await page.wait_for_timeout(2500)
                    clicked = True
                    print(f"CLICKED_LIVE selector={selector}")
                    break
            except Exception:
                pass
        rows = page.locator("div[id*='g_1_']")
        count = await rows.count()
        print(f"ROWS_AFTER_LIVE_FILTER {count} clicked={clicked}")
        for i in range(count):
            row = rows.nth(i)
            rid = await row.get_attribute("id") or ""
            mid = rid.split("g_1_",1)[-1].split("_",1)[0]
            if len(mid) != 8 or not mid.isalnum():
                continue
            text = " | ".join(x.strip() for x in (await row.inner_text()).splitlines() if x.strip())
            # If LIVE click failed, only accept rows visibly showing minute/HT/2nd-half style statuses.
            liveish = bool(re.search(r"(?:^|\|\s)(?:HT|LIVE|\d{1,2}'|\d{1,2}:\d{2})", text, re.I))
            if clicked or liveish:
                found.append((mid, text))
                print(f"LIVE_ROW {mid} {text[:220]}")
        await browser.close()
    return found


async def main():
    rows = await discover_live_rows()
    print(f"TRUE_LIVE_CANDIDATES {len(rows)}")
    for mid, text in rows[:40]:
        print(f"TRY {mid} {text[:180]}")
        body = fetch_stats(mid)
        if not body:
            continue
        print(f"SUCCESS match={mid} bytes={len(body)} prefix={body[:240]!r}")
        raw_stat_fragments(body)
        return
    print("NO_LIVE_STATS_FOUND")


if __name__ == "__main__":
    asyncio.run(main())
