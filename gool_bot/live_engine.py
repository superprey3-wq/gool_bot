"""Flashscore live statistics + goal pressure engine."""
from __future__ import annotations

import json, logging, os, re, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import requests
from playwright.async_api import async_playwright

logger=logging.getLogger("live_engine")
FLASH_URL="https://www.flashscore.com/football/"; FSIGN=os.getenv("FLASHSCORE_FSIGN","SW9D1eZo"); FEED_HOSTS=("global","2","46")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"; STATE_FILE=Path(os.getenv("LIVE_STATE_FILE","live_state.json"))
STAT_MAP={"432":"xg","499":"xgot","12":"possession","34":"shots","13":"shots_on_target","14":"shots_off_target","158":"blocked_shots","461":"shots_inside_box","463":"shots_outside_box","459":"big_chances","16":"corners","471":"touches_box","23":"yellow_cards"}
INVALID_LEAGUES={"draw","home","away","odds","live","finished","scheduled","standings"}

@dataclass
class LiveMatch:
    event_id:str; minute:int; home:str; away:str; home_score:int; away_score:int; status:str; league:str=""; is_halftime:bool=False
@dataclass
class StatsSnapshot:
    ts:int; minute:int; values:dict[str,tuple[float,float]]
@dataclass
class GoalPressureResult:
    score:float; momentum:float; quality:float; context:float; reasons:list[str]

def _to_number(v):
    try:return float(str(v).strip().replace("%",""))
    except ValueError:return 0.0

def _feed(path:str)->str:
    headers={"User-Agent":UA,"x-fsign":FSIGN,"Origin":"https://www.flashscore.com","Referer":"https://www.flashscore.com/","Accept":"*/*"}
    for host in FEED_HOSTS:
        try:
            r=requests.get(f"https://{host}.flashscore.ninja/2/x/feed/{path}",headers=headers,timeout=12)
            if r.status_code==200 and r.text.strip() and not r.text.lstrip().lower().startswith("<"): return r.text
        except requests.RequestException: pass
    return ""
def fetch_stats(event_id): return _feed(f"df_st_1_{event_id}")
def fetch_summary(event_id): return _feed(f"df_sui_1_{event_id}")

def parse_goal_timeline(body:str)->list[str]:
    goals=[]; last=(0,0)
    for chunk in body.split("~III"):
        if not chunk: continue
        minute_m=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})(?:'|\\')?",chunk)
        h_m=re.search(r"INX(?:÷|¬)(\d+)",chunk); a_m=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
        if not minute_m or (not h_m and not a_m): continue
        h=int(h_m.group(1)) if h_m else last[0]; a=int(a_m.group(1)) if a_m else last[1]
        if h>last[0] or a>last[1]:
            side="хозяева" if h>last[0] else "гости"; goals.append(f"{minute_m.group(1)}' {side}"); last=(h,a)
    return goals

def parse_stats(body):
    out={}
    for chunk in body.split("~"):
        m=re.search(r"SD(?:÷|¬)(\d+).*?SH(?:÷|¬)([^¬~]+).*?SI(?:÷|¬)([^¬~]+)",chunk)
        if m:
            sid,h,a=m.groups(); name=STAT_MAP.get(sid)
            if name: out[name]=(_to_number(h),_to_number(a))
    return out

def load_state():
    if not STATE_FILE.exists(): return {}
    try:return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:return {}
def save_snapshot(event_id,snapshot):
    state=load_state(); rows=state.setdefault(event_id,[]); rows.append(asdict(snapshot)); cutoff=int(time.time())-7200
    state[event_id]=[r for r in rows if int(r.get("ts",0))>=cutoff][-30:]; STATE_FILE.write_text(json.dumps(state,ensure_ascii=False),encoding="utf-8")
def _delta(values,prev,key):
    a=values.get(key,(0.,0.)); b=prev.get(key,(0.,0.)); return max(0.,(a[0]+a[1])-(b[0]+b[1]))
def calculate_goal_pressure(match,values,previous=None):
    previous=previous or {}; xg=sum(values.get("xg",(0,0))); shots=sum(values.get("shots",(0,0))); sot=sum(values.get("shots_on_target",(0,0))); big=sum(values.get("big_chances",(0,0))); inside=sum(values.get("shots_inside_box",(0,0))); touches=sum(values.get("touches_box",(0,0))); corners=sum(values.get("corners",(0,0)))
    quality=min(100.,xg*24+sot*5+big*10+inside*1.7+touches*.45); dxg=_delta(values,previous,"xg"); dshots=_delta(values,previous,"shots"); dsot=_delta(values,previous,"shots_on_target"); dbig=_delta(values,previous,"big_chances"); dinside=_delta(values,previous,"shots_inside_box"); dtouches=_delta(values,previous,"touches_box"); dcorners=_delta(values,previous,"corners")
    momentum=min(100.,dxg*42+dshots*7+dsot*13+dbig*18+dinside*4+dtouches*1.4+dcorners*5); goals=match.home_score+match.away_score
    context=65. if match.minute<=45 and goals<=1 else 45. if match.minute<=45 else 75. if match.minute<=75 and goals<=2 else 55. if match.minute<=75 else 70. if goals<=3 else 45.; activity=min(100.,shots*2.2+sot*5.5+corners*1.8); score=min(100.,quality*.38+momentum*.37+activity*.15+context*.10)
    reasons=[]
    if dxg>=.35: reasons.append(f"xG +{dxg:.2f} за последнее окно")
    if dsot>=2: reasons.append(f"+{int(dsot)} удара в створ")
    if dshots>=4: reasons.append(f"+{int(dshots)} ударов")
    if dbig>=1: reasons.append("появился большой момент")
    if dtouches>=8: reasons.append(f"+{int(dtouches)} касаний в штрафной")
    if not reasons and score>=70: reasons.append("высокое суммарное давление")
    return GoalPressureResult(round(score,1),round(momentum,1),round(quality,1),round(context,1),reasons)

async def discover_live_matches():
    matches=[]
    skipped={"bad_id":0,"empty":0,"no_minute":0,"no_names_or_score":0}
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        context=await browser.new_context(user_agent=UA,locale="en-GB",timezone_id="UTC",viewport={"width":1440,"height":1200})
        page=await context.new_page(); await page.goto(FLASH_URL,wait_until="domcontentloaded",timeout=35000); await page.wait_for_timeout(4500)
        for selector in ["text=LIVE","[data-testid='wcl-tab']:has-text('LIVE')","button:has-text('LIVE')"]:
            try:
                loc=page.locator(selector)
                if await loc.count(): await loc.first.click(timeout=3000); await page.wait_for_timeout(1800); break
            except Exception: pass

        # Flashscore lazy-renders the fixture list. Scroll until row count stops growing.
        last_count=-1; stable=0
        for _ in range(14):
            rows_now=page.locator("div[id*='g_1_']"); count=await rows_now.count()
            if count==last_count: stable+=1
            else: stable=0; last_count=count
            if stable>=3: break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(700)
        await page.evaluate("window.scrollTo(0, 0)"); await page.wait_for_timeout(300)

        rows=page.locator("div[id*='g_1_']"); dom_count=await rows.count(); logger.info("Flashscore LIVE DOM-строк после прокрутки: %d",dom_count)
        for i in range(dom_count):
            row=rows.nth(i); rid=await row.get_attribute("id") or ""; event_id=rid.split("g_1_",1)[-1].split("_",1)[0]
            if len(event_id)!=8 or not event_id.isalnum(): skipped["bad_id"]+=1; continue
            lines=[x.strip() for x in (await row.inner_text()).splitlines() if x.strip()]
            if not lines: skipped["empty"]+=1; continue
            text=" | ".join(lines); first=lines[0]; is_halftime=bool(re.search(r"Half Time|HT|Перерыв",first,re.I)); mm=re.match(r"^(\d{1,3})(?:\+(\d+))?(?:'|\b)",first); minute=int(mm.group(1)) if mm else 45 if is_halftime else 0
            if not minute: skipped["no_minute"]+=1; continue
            names=[]
            for selector in [".event__participant--home",".event__participant--away","[class*='participant--home']","[class*='participant--away']"]:
                loc=row.locator(selector)
                if await loc.count():
                    v=(await loc.first.inner_text()).strip()
                    if v and v not in names:names.append(v)
            if len(names)<2:
                cand=[v for v in lines[1:] if not re.fullmatch(r"\d+",v) and re.search(r"[A-Za-zА-Яа-я]",v)][:2]; names=cand
            scores=[int(x) for x in lines[1:] if re.fullmatch(r"\d+",x)]; league=""
            try:
                header=row.locator("xpath=preceding::div[contains(@class,'event__header') or contains(@class,'event__title')][1]")
                if await header.count(): league=" ".join((await header.first.inner_text()).split())[:120]
            except Exception: pass
            if league.lower().strip() in INVALID_LEAGUES: league=""
            if len(names)>=2 and len(scores)>=2: matches.append(LiveMatch(event_id,minute,names[0],names[1],scores[-2],scores[-1],text[:180],league,is_halftime))
            else: skipped["no_names_or_score"]+=1
        logger.info("LIVE discovery: DOM=%d, распознано=%d, пропущено=%s",dom_count,len(matches),skipped)
        await browser.close()
    return matches

def get_previous_values(event_id,current_minute,lookback_minutes=8):
    state=load_state().get(event_id,[]); target=current_minute-lookback_minutes; candidates=[r for r in state if int(r.get("minute",999))<=target]
    if not candidates:return None
    return {k:tuple(v) for k,v in candidates[-1].get("values",{}).items()}
