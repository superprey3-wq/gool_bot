from __future__ import annotations
import asyncio,re,requests
from playwright.async_api import async_playwright
URL='https://www.flashscore.com/football/'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36'
NEEDLES=['getLiveOddsBettingTypeMenu','findLiveOdds','LiveOdds','lobtm','LIVE_ODDS','liveOdds','findOddsForBookmaker']

async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  c=await b.new_context(user_agent=UA,locale='en-GB',timezone_id='UTC',viewport={'width':1440,'height':1200})
  page=await c.new_page(); scripts=set()
  async def resp(r):
   u=r.url
   if u.endswith('.js') or '.js?' in u: scripts.add(u)
  page.on('response',resp)
  await page.goto(URL,wait_until='domcontentloaded',timeout=35000); await page.wait_for_timeout(5000)
  rows=page.locator("div[id*='g_1_'].event__match--live")
  target=None
  for i in range(await rows.count()):
   row=rows.nth(i); txt=' '.join((await row.inner_text()).split()); m=re.match(r'(\d{1,2})\b',txt)
   if not m or not (10<=int(m.group(1))<=80):continue
   for j in range(await row.locator('a').count()):
    href=await row.locator('a').nth(j).get_attribute('href')
    if href and '/match/' in href:
     target='https://www.flashscore.com'+href if href.startswith('/') else href; break
   if target:break
  if target:
   await page.goto(target,wait_until='domcontentloaded',timeout=35000); await page.wait_for_timeout(5000)
   print('TARGET',target)
  print('SCRIPTS',len(scripts))
  await b.close()
 headers={'User-Agent':UA,'Referer':'https://www.flashscore.com/'}
 hits=0
 for idx,u in enumerate(sorted(scripts)):
  try:
   r=requests.get(u,headers=headers,timeout=20); text=r.text
  except Exception as e:
   continue
  found=[n for n in NEEDLES if n in text]
  if not found:continue
  hits+=1; print('JS_HIT',idx,'bytes',len(text),'needles',found,'url',u)
  for needle in found:
   pos=0; shown=0
   while shown<5:
    pos=text.find(needle,pos)
    if pos<0:break
    lo=max(0,pos-900); hi=min(len(text),pos+1400)
    snippet=text[lo:hi].replace('\n',' ')
    print('SNIP',needle,repr(snippet))
    pos+=len(needle); shown+=1
 print('TOTAL_HIT_FILES',hits)
if __name__=='__main__':asyncio.run(main())
