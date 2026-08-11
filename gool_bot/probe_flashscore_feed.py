from __future__ import annotations
import asyncio, json, requests
from playwright.async_api import async_playwright
URL="https://www.flashscore.com/football/"; UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"; LS="https://global.ds.lsapp.eu/odds/pq_graphql"; H={"User-Agent":UA,"Accept":"application/json, text/plain, */*","Referer":"https://www.flashscore.com/"}
def parse(body):
 out=[]
 for raw in body.split("~AA÷")[1:]:
  eid,sep,rest=raw.partition("¬"); f={}
  if not sep or len(eid)!=8: continue
  for t in rest.split("¬"):
   if "÷" in t:
    k,v=t.split("÷",1); f.setdefault(k,v)
  out.append((eid,f))
 return out
def query(eid,hashv,project,geo,sub):
 p={"_hash":hashv,"eventId":eid,"projectId":project,"geoIpCode":geo,"geoIpSubdivisionCode":sub}
 r=requests.get(LS,params=p,headers=H,timeout=20); print("Q",hashv,project,geo,"status",r.status_code,"bytes",len(r.text))
 try: d=r.json()
 except: return
 print("ROOT",json.dumps(d.get('data',{}),ensure_ascii=False)[:500])
 odds=d.get("data",{}).get("findOddsByEventId",{}).get("odds",[]) or []
 print("ENTRIES",len(odds))
 for scope in ("FIRST_HALF","SECOND_HALF","FULL_TIME"):
  rows=[]
  for e in odds:
   if e.get("bettingType")!="OVER_UNDER" or e.get("bettingScope")!=scope: continue
   meta=(e.get("bookmakerId"),e.get("hasLiveBettingOffers"))
   for x in e.get("odds") or []:
    if x.get("selection")=="OVER" and x.get("active",True): rows.append((meta,(x.get("handicap") or {}).get("value"),x.get("value"),x.get("opening")))
  print(scope,"SAMPLE",rows[:12])
async def main():
 master=None
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"]); c=await b.new_context(user_agent=UA); page=await c.new_page()
  async def resp(r):
   nonlocal master
   if "f_1_0_0_en_1" in r.url:
    try: master=await r.text()
    except: pass
  page.on("response",resp); await page.goto(URL,wait_until="domcontentloaded",timeout=35000); await page.wait_for_timeout(5000); await b.close()
 if not master:return
 live=[(e,f) for e,f in parse(master) if f.get("AB")=="2"]
 # choose a normal live event, preferably second half
 pick=next(((e,f) for e,f in live if f.get("AC")=="13"),live[0])
 eid,f=pick; print("MATCH",eid,f.get("AE"),f.get("AF"),"score",f.get("AG"),f.get("AH"),"AC",f.get("AC"))
 for q in [("oce","5","US","USCA"),("ope","5","US","USCA"),("oce","46","RU","RUMOW"),("ope","46","RU","RUMOW")]: query(eid,*q)
if __name__=="__main__":asyncio.run(main())
