from __future__ import annotations
import asyncio, json, requests
from playwright.async_api import async_playwright
URL="https://www.flashscore.com/football/"; UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"; H={"User-Agent":UA,"Accept":"application/json, text/plain, */*","Referer":"https://www.flashscore.com/"}
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
def query(url,eid):
 p={"_hash":"ope","eventId":eid,"projectId":"46","geoIpCode":"RU","geoIpSubdivisionCode":"RUMOW"}
 r=requests.get(url,params=p,headers=H,timeout=20); print("URL",url,"status",r.status_code,"bytes",len(r.text))
 try:d=r.json()
 except:return
 print("DATAKEYS",list((d.get('data') or {}).keys()))
 print("DATA",json.dumps(d.get('data',{}),ensure_ascii=False)[:1200])
async def main():
 master=None
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"]); c=await b.new_context(user_agent=UA); page=await c.new_page()
  async def resp(r):
   nonlocal master
   if "f_1_0_0_en_1" in r.url:
    try:master=await r.text()
    except:pass
  page.on("response",resp); await page.goto(URL,wait_until="domcontentloaded",timeout=35000); await page.wait_for_timeout(5000); await b.close()
 live=[(e,f) for e,f in parse(master or '') if f.get('AB')=='2']; pick=next(((e,f) for e,f in live if f.get('AC')=='13'),live[0]); eid,f=pick
 print("MATCH",eid,f.get('AE'),f.get('AF'),f.get('AG'),f.get('AH'),f.get('AC'))
 for u in ["https://46.ds.lsapp.eu/pq_graphql","https://global.ds.lsapp.eu/pq_graphql","https://46.ds.lsapp.eu/odds/pq_graphql"]: query(u,eid)
if __name__=='__main__':asyncio.run(main())
