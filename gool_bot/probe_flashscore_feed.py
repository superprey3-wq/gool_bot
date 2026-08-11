from __future__ import annotations
import asyncio,re
from playwright.async_api import async_playwright
URL='https://www.flashscore.com/football/'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36'

async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  c=await b.new_context(user_agent=UA,locale='en-GB',timezone_id='UTC',viewport={'width':1440,'height':1200})
  page=await c.new_page(); captured=[]
  async def resp(r):
   if 'lsapp.eu' not in r.url: return
   try: body=await r.text()
   except: body=''
   captured.append((r.status,r.url,len(body),body[:1000].replace('\n',' ')))
  page.on('response',resp)
  await page.goto(URL,wait_until='domcontentloaded',timeout=35000); await page.wait_for_timeout(5000)
  rows=page.locator("div[id*='g_1_'].event__match--live")
  print('LIVE_ROWS',await rows.count())
  candidates=[]
  for i in range(await rows.count()):
   row=rows.nth(i); txt=' '.join((await row.inner_text()).split()); m=re.match(r'(\d{1,2})\b',txt)
   if not m or not (10<=int(m.group(1))<=80): continue
   for j in range(await row.locator('a').count()):
    href=await row.locator('a').nth(j).get_attribute('href')
    if href and '/match/' in href:
     candidates.append(('https://www.flashscore.com'+href if href.startswith('/') else href,txt)); break
  for target in candidates[:8]:
   print('TRY',target[0],target[1]); captured.clear()
   try:
    await page.goto(target[0],wait_until='domcontentloaded',timeout=30000); await page.wait_for_timeout(3500)
   except: continue
   # Open summary odds section, then explicitly click over/under if present.
   for pat in ['Odds','ODDS']:
    loc=page.get_by_text(pat,exact=True)
    try:
     if await loc.count(): await loc.first.click(timeout=2500); await page.wait_for_timeout(1800); break
    except: pass
   clicked=False
   for pat in ['Over/Under','Over / Under','Total','Totals']:
    loc=page.get_by_text(pat,exact=False)
    try:
     if await loc.count():
      print('FOUND_TAB',pat,await loc.count()); await loc.first.click(timeout=3000); await page.wait_for_timeout(3000); clicked=True; break
    except Exception as e: print('CLICK_ERR',pat,str(e)[:120])
   body=' '.join((await page.locator('body').inner_text()).split())
   print('HAS_OVER_UNDER_TEXT',('OVER/UNDER' in body.upper()),'CLICKED_OU',clicked)
   # If we captured a live-odds payload beyond the menu, stop at this match.
   for status,url,size,sample in captured:
    print('NET',status,size,url); print('SAMPLE',sample)
   if any('_hash=lo' in u.lower() and '_hash=lobtm' not in u.lower() for _,u,_,_ in captured):
    print('FOUND_LIVE_ODDS_REQUEST'); break
  await b.close()
if __name__=='__main__':asyncio.run(main())
