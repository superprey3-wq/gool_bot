from __future__ import annotations
import asyncio
from playwright.async_api import async_playwright
URL='https://www.flashscore.com/football/'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36'

async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  c=await b.new_context(user_agent=UA,locale='en-GB',timezone_id='UTC',viewport={'width':1440,'height':1200})
  page=await c.new_page(); captured=[]
  async def resp(r):
   u=r.url.lower()
   if 'lsapp' in u or '/odds/' in u or 'pq_graphql' in u:
    try: body=await r.text()
    except: body=''
    captured.append((r.status,r.url,len(body),body[:500].replace('\n',' ')))
  page.on('response',resp)
  await page.goto(URL,wait_until='domcontentloaded',timeout=35000); await page.wait_for_timeout(5000)
  rows=page.locator("div[id*='g_1_'].event__match--live")
  print('LIVE_ROWS',await rows.count())
  target=None
  for i in range(await rows.count()):
   row=rows.nth(i); txt=' '.join((await row.inner_text()).split())
   # Prefer a normal regulation-time match, not HT/extra time.
   import re
   m=re.match(r'(\d{1,2})\b',txt)
   if m and 10<=int(m.group(1))<=80:
    anchors=row.locator('a')
    for j in range(await anchors.count()):
     href=await anchors.nth(j).get_attribute('href')
     if href and '/match/' in href:
      target=('https://www.flashscore.com'+href if href.startswith('/') else href,txt); break
   if target:break
  if not target:
   print('NO_TARGET'); await b.close(); return
  print('TARGET',target[0],target[1])
  captured.clear(); await page.goto(target[0],wait_until='domcontentloaded',timeout=35000); await page.wait_for_timeout(4500)
  print('PAGE',page.url)
  # Click an Odds/Odds comparison tab if present.
  for pat in ['Odds','Over/Under','O/U']:
   loc=page.get_by_text(pat,exact=False)
   try:
    if await loc.count():
     await loc.first.click(timeout=3000); await page.wait_for_timeout(3500); print('CLICKED',pat); break
   except: pass
  # Also try common hash routes based on current match URL.
  for suffix in ['#/odds-comparison/over-under/full-time','#/odds-comparison/over-under/1st-half']:
   try:
    base=target[0].split('#',1)[0]; await page.goto(base+suffix,wait_until='domcontentloaded',timeout=25000); await page.wait_for_timeout(3000)
   except: pass
  print('CAPTURED',len(captured))
  seen=set()
  for status,url,size,sample in captured:
   key=url
   if key in seen:continue
   seen.add(key); print('NET',status,size,url); print('SAMPLE',sample)
  # Print visible price-like text around odds page for comparison.
  txt=' '.join((await page.locator('body').inner_text()).split())
  print('BODY_SAMPLE',txt[:5000])
  await b.close()
if __name__=='__main__':asyncio.run(main())
