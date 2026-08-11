from __future__ import annotations

import asyncio
import re
from collections import Counter
from playwright.async_api import async_playwright

URL = "https://www.flashscore.com/football/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"

PATTERNS = {
    "AA_div": r"~AA÷([A-Za-z0-9]{8})",
    "AA_not": r"~AA¬([A-Za-z0-9]{8})",
    "AA_any": r"~AA[÷¬]([A-Za-z0-9]{8})",
    "event_id": r"(?:~|^)AA[÷¬]([A-Za-z0-9]{8})",
}


def event_counts(body: str) -> dict[str, int]:
    return {name: len(set(re.findall(pattern, body))) for name, pattern in PATTERNS.items()}


async def probe(locale: str):
    feed_rows = []
    master_sample = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent=UA,
            locale=locale,
            timezone_id="UTC",
            viewport={"width": 1440, "height": 1200},
        )
        page = await context.new_page()

        async def on_response(response):
            nonlocal master_sample
            url = response.url
            if "/x/feed/" not in url:
                return
            try:
                body = await response.text()
            except Exception:
                return
            counts = event_counts(body)
            feed_rows.append((url, response.status, len(body), counts))
            if "f_1_0_0_en_1" in url and master_sample is None:
                master_sample = body

        page.on("response", on_response)
        await page.goto(URL, wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(5000)
        for _ in range(14):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(450)
        await page.wait_for_timeout(1200)

        all_rows = page.locator("div[id*='g_1_']")
        live_rows = page.locator("div[id*='g_1_'].event__match--live")
        print(f"LOCALE {locale}: DOM all={await all_rows.count()} live={await live_rows.count()}")

        seen = set()
        for url, status, size, counts in sorted(feed_rows, key=lambda x: (-max(x[3].values(), default=0), -x[2])):
            key = (url, status, size, tuple(sorted(counts.items())))
            if key in seen:
                continue
            seen.add(key)
            print(f"FEED {locale}: counts={counts} bytes={size} status={status} url={url}")

        families = Counter()
        for url, _status, _size, counts in feed_rows:
            path = url.split('/x/feed/', 1)[-1].split('?', 1)[0]
            family = path.split('_', 1)[0]
            families[(family, max(counts.values(), default=0))] += 1
        print(f"FAMILIES {locale}: {families.most_common(20)}")

        if master_sample is not None:
            sample = master_sample[:3000]
            print(f"MASTER_PREFIX {locale}: {sample!r}")
            for token in ("AA÷", "AA¬", "AC÷", "AC¬", "AE÷", "AF÷", "AG÷", "AH÷", "AD÷"):
                print(f"TOKEN {locale} {token}: {master_sample.count(token)}")

        await browser.close()


async def main():
    for locale in ("en-GB", "ru-RU"):
        try:
            await probe(locale)
        except Exception as exc:
            print(f"ERROR {locale}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
