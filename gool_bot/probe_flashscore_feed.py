from __future__ import annotations
import asyncio,json,requests,re,runpy
from playwright.async_api import async_playwright
from live_engine import _feed
URL='https://www.flashscore.com/football/'
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36'
H={'User-Agent':UA,'Accept':'application/json, text/plain, */*','Referer':'https://www.flashscore.com/'}
ROOT='https://2.ds.lsapp.eu/pq_graphql'

def get(params):
 r=requests.get(ROOT,params=params,headers=H,timeout=20)
 print('GET',r.status_code,r.url,'bytes',len(r.text))
 try:return r.json()
 except:return {}

async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  c=await b.new_context(user_agent=UA,locale='en-GB',timezone_id='UTC',viewport={'width':1440,'height':1200})
  page=await c.new_page(); await page.goto(URL,wait_until='domcontentloaded',timeout=35000); await page.wait_for_timeout(5000)
  rows=page.locator("div[id*='g_1_'].event__match--live")
  tests=[]
  for i in range(await rows.count()):
   row=rows.nth(i); rid=await row.get_attribute('id') or ''; eid=rid.split('g_1_',1)[-1].split('_',1)[0]
   txt=' '.join((await row.inner_text()).split()); m=re.match(r'(\d{1,2})\b',txt)
   if len(eid)==8 and m and 10<=int(m.group(1))<=80: tests.append((eid,txt))
  await b.close()
 for eid,txt in tests[:12]:
  print('\nMATCH',eid,txt)
  hh=_feed(f'df_hh_1_{eid}')
  print('H2H_BYTES',len(hh))
  if hh:print('H2H_RAW',hh[:12000])
  menu=get({'_hash':'lobtm','eventId':eid,'projectId':'2','geoIpCode':'US','geoIpSubdivisionCode':'USAZ'})
  obj=(menu.get('data') or {}).get('getLiveOddsBettingTypeMenu') or {}; settings=obj.get('settings') or {}; book_names={}
  for pb in settings.get('bookmakers') or []:
   bm=pb.get('bookmaker') or {}; book_names[bm.get('id')]=bm.get('name')
  items=[x for x in (obj.get('items') or []) if x.get('isActive') and x.get('bettingType')=='OVER_UNDER' and 'LIVE' in (x.get('types') or [])]
  print('ACTIVE_OU_MENU',json.dumps(items,ensure_ascii=False))
  if not items:continue
  found=False
  for item in items:
   for bid in item.get('bookmakerIds') or []:
    p={'_hash':'ole2','eventId':eid,'bookmakerId':bid,'betType':'OVER_UNDER','betScope':item.get('bettingScope')}
    d=get(p); live=(d.get('data') or {}).get('findLiveOddsForBookmaker')
    print('BOOK',bid,book_names.get(bid),'SCOPE',item.get('bettingScope'),'LIVE',json.dumps(live,ensure_ascii=False)[:5000])
    if live:found=True; break
   if found:break
  if hh:break

if __name__=='__main__':
 asyncio.run(main())
 print('\n=== FOTMOB + SOFASCORE COVERAGE ===')
 runpy.run_path('../tests/source_coverage_probe.py',run_name='__main__')
# rerun after EasySoccerData dependency fix
