"""Prematch totals movement scanner using Flashscore/LSApp."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import async_playwright
from signal_journal import add_signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prematch_scanner")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MIN_MINUTES_TO_KICKOFF = int(os.getenv("MIN_MINUTES_TO_KICKOFF", "2"))
MAX_MINUTES_TO_KICKOFF = int(os.getenv("MAX_MINUTES_TO_KICKOFF", "9"))
MIN_BOOKMAKERS = int(os.getenv("MIN_BOOKMAKERS", "3"))
MIN_CONSENSUS = float(os.getenv("MIN_CONSENSUS", "0.65"))
MIN_MEDIAN_DROP = float(os.getenv("MIN_MEDIAN_DROP", "8.0"))
MAX_SIGNALS_PER_MATCH = int(os.getenv("MAX_SIGNALS_PER_MATCH", "4"))

MOSCOW = ZoneInfo("Europe/Moscow")
LSAPP_URL = "https://global.ds.lsapp.eu/odds/pq_graphql"
FLASH_URLS = ["https://www.flashscore.com/football/", "https://www.flashscore.co.uk/football/"]
HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36","Accept":"application/json, text/plain, */*","Referer":"https://www.flashscore.com/"}
SCOPE_LABELS = {"FULL_TIME":"Матч","FIRST_HALF":"1-й тайм","SECOND_HALF":"2-й тайм"}
COUNTRY_RU={"Bul":"Болгария","Gre":"Греция","Nor":"Норвегия","Bel":"Бельгия","Aze":"Азербайджан","Den":"Дания","Eng":"Англия","Esp":"Испания","Ita":"Италия","Ger":"Германия","Fra":"Франция"}
KNOWN_RU={"CSKA":"ЦСКА","Sofia":"София","Panathinaikos":"Панатинаикос","Bodo/Glimt":"Буде/Глимт","Royale Union SG":"Юнион Сент-Жиллуаз","Sabah Baku":"Сабах Баку","Aarhus":"Орхус"}

@dataclass
class Match:
    event_id:str; home:str; away:str; kickoff:datetime; league:str=""
@dataclass
class MovementSignal:
    market:str; scope:str; line:str; side:str; median_open:float; median_current:float; median_drop:float; consensus:float; bookmakers:int; score:float

def _safe_float(value:Any)->float|None:
    try:return float(value)
    except (TypeError,ValueError):return None

def _ru_name(name:str)->str:
    text=name.strip(); country=""; m=re.search(r"\s*\(([A-Za-z]{3})\)\s*$",text)
    if m:country=COUNTRY_RU.get(m.group(1),m.group(1)); text=text[:m.start()].strip()
    for src,dst in sorted(KNOWN_RU.items(),key=lambda kv:-len(kv[0])):text=text.replace(src,dst)
    pairs=[("shch","щ"),("sch","щ"),("zh","ж"),("kh","х"),("ts","ц"),("ch","ч"),("sh","ш"),("yu","ю"),("ya","я"),("yo","ё")]
    def translit_word(w:str)->str:
        if not re.search(r"[A-Za-z]",w):return w
        low=w.lower()
        for a,b in pairs:low=low.replace(a,b)
        low=low.translate(str.maketrans("abvgdezijklmnoprstufhycqxw","абвгдезийклмнопрстуфхыцкв"))
        return low[:1].upper()+low[1:] if w[:1].isupper() else low
    text=" ".join(translit_word(w) if re.search(r"[A-Za-z]",w) else w for w in text.split())
    return f"{text} ({country})" if country else text

def _ru_league(value:str)->str:
    if not value:return "Турнир не определён"
    replacements={"Champions League":"Лига чемпионов","Europa League":"Лига Европы","Conference League":"Лига конференций","Friendly":"Товарищеский матч","Club Friendly":"Клубный товарищеский матч"}; out=value
    for a,b in replacements.items():out=out.replace(a,b)
    return out

def _feed_endpoints(day:datetime)->list[str]:
    vals=[day.strftime("%Y%m%d"),day.strftime("%Y-%m-%d"),day.strftime("%d-%m-%Y")]; result=[]
    for v in vals:result += [f"https://d.flashscore.com/x/feed/f_{v}",f"https://d.flashscore.com/x/feed/dt_{v}",f"https://www.flashscore.com/x/feed/f_{v}"]
    return result

def _parse_feed(text:str)->list[Match]:
    found={}
    for raw in text.split("~AA¬")[1:]:
        event_id,sep,rest=raw.partition("¬")
        if not sep or len(event_id)!=8 or not event_id.isalnum():continue
        tokens=rest.split("¬"); fields={}
        for i in range(len(tokens)-1):
            if re.fullmatch(r"[A-Z]{1,3}",tokens[i]):fields[tokens[i]]=tokens[i+1].split("~",1)[0]
        try:kickoff=datetime.fromtimestamp(int(fields.get("AD","")),UTC)
        except (TypeError,ValueError):continue
        home,away=fields.get("AE","").strip(),fields.get("AF","").strip(); league=(fields.get("ZA","") or fields.get("CX","") or fields.get("ZB","")).strip()
        if home and away:found[event_id]=Match(event_id,home,away,kickoff,league)
    return list(found.values())
def _discover_from_feeds()->list[Match]:
    now=datetime.now(UTC); found={}
    for day in (now,now+timedelta(days=1)):
        for endpoint in _feed_endpoints(day):
            try:r=requests.get(endpoint,headers=HEADERS,timeout=10)
            except requests.RequestException:continue
            if r.status_code==200 and "~AA¬" in r.text:
                parsed=_parse_feed(r.text)
                if parsed:found.update({m.event_id:m for m in parsed}); break
    return list(found.values())
def _parse_clock(text:str,now:datetime)->datetime|None:
    m=re.search(r"(?:(\d{1,2})\.(\d{1,2})\.\s*)?(\d{1,2}):(\d{2})"," ".join(text.split()))
    if not m:return None
    d,mo,h,mi=m.groups()
    if d and mo:
        try:c=datetime(now.year,int(mo),int(d),int(h),int(mi),tzinfo=UTC)
        except ValueError:return None
        if c<now-timedelta(days=180):c=c.replace(year=now.year+1)
        return c
    return now.replace(hour=int(h),minute=int(mi),second=0,microsecond=0)

async def _discover_from_browser()->list[Match]:
    now=datetime.now(UTC); found={}
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"]); context=await browser.new_context(user_agent=HEADERS["User-Agent"],locale="ru-RU",timezone_id="UTC",viewport={"width":1440,"height":1200}); page=await context.new_page()
        for url in FLASH_URLS:
            try:
                await page.goto(url,wait_until="domcontentloaded",timeout=35000); await page.wait_for_timeout(4500)
                for _ in range(4):await page.mouse.wheel(0,1400); await page.wait_for_timeout(600)
                rows=page.locator("div[id*='g_1_']")
                for i in range(await rows.count()):
                    row=rows.nth(i); rid=await row.get_attribute("id") or ""; mid=rid.split("g_1_",1)[-1].split("_",1)[0]
                    if len(mid)!=8 or not mid.isalnum():continue
                    text=(await row.inner_text()).strip(); kickoff=_parse_clock(text,now)
                    if not kickoff:continue
                    names=[]
                    for sel in [".event__participant--home",".event__participant--away","[class*='participant--home']","[class*='participant--away']"]:
                        loc=row.locator(sel)
                        if await loc.count():
                            v=(await loc.first.inner_text()).strip()
                            if v and v not in names:names.append(v)
                    if len(names)<2:
                        lines=[x.strip() for x in text.splitlines() if x.strip()]; names=[x for x in lines if re.search(r"[A-Za-zА-Яа-я]",x) and not re.fullmatch(r"\d{1,2}:\d{2}",x)][:2]
                    league=""
                    try:
                        header=row.locator("xpath=preceding::div[contains(@class,'header') or contains(@class,'event__title')][1]")
                        if await header.count():league=" ".join((await header.first.inner_text()).split())[:140]
                    except Exception:pass
                    if len(names)>=2:found[mid]=Match(mid,names[0],names[1],kickoff,league)
                if found:break
            except Exception as exc:logger.warning("Flashscore browser discovery failed %s: %s",url,str(exc)[:180])
        await browser.close()
    return list(found.values())
def _discover_matches()->list[Match]:
    now=datetime.now(UTC); matches=_discover_from_feeds()
    try:
        browser=asyncio.run(_discover_from_browser()); by_id={m.event_id:m for m in matches}
        for b in browser:
            if b.event_id in by_id:
                base=by_id[b.event_id]; base.home=b.home or base.home; base.away=b.away or base.away; base.league=b.league or base.league
            else:by_id[b.event_id]=b
        matches=list(by_id.values())
    except Exception as exc:logger.warning("Browser metadata merge failed: %s",exc)
    upcoming=[m for m in matches if MIN_MINUTES_TO_KICKOFF <= (m.kickoff-now).total_seconds()/60 <= MAX_MINUTES_TO_KICKOFF]
    return sorted(upcoming,key=lambda m:m.kickoff)

def _fetch_event_odds(event_id:str)->list[dict[str,Any]]:
    params={"_hash":"oce","eventId":event_id,"projectId":"5","geoIpCode":"US","geoIpSubdivisionCode":"USCA"}
    try:r=requests.get(LSAPP_URL,params=params,headers=HEADERS,timeout=25); r.raise_for_status(); payload=r.json()
    except (requests.RequestException,ValueError) as exc:logger.warning("LSApp failed %s: %s",event_id,exc); return []
    entries=payload.get("data",{}).get("findOddsByEventId",{}).get("odds",[]); return [x for x in entries if isinstance(x,dict)] if isinstance(entries,list) else []
def _participant_map(entries,match):
    for entry in entries:
        if entry.get("bettingType")!="HOME_DRAW_AWAY":continue
        ids=[]
        for item in entry.get("odds",[]) or []:
            if isinstance(item,dict) and item.get("eventParticipantId") is not None and item.get("eventParticipantId") not in ids:ids.append(item.get("eventParticipantId"))
        if len(ids)>=2:return {ids[0]:match.home,ids[1]:match.away}
    return {}
def _extract_signals(entries,match):
    participant_names=_participant_map(entries,match); buckets={}
    for entry in entries:
        bt=str(entry.get("bettingType") or ""); scope=str(entry.get("bettingScope") or "FULL_TIME"); items=entry.get("odds") or []
        if not isinstance(items,list) or not (bt=="OVER_UNDER" or ("TOTAL" in bt and "SCORE" not in bt)):continue
        for item in items:
            if not isinstance(item,dict) or not item.get("active",True):continue
            opening,current=_safe_float(item.get("opening")),_safe_float(item.get("value")); handicap=item.get("handicap") or {}; line=handicap.get("value") if isinstance(handicap,dict) else None; selection=str(item.get("selection") or "").upper()
            if opening is None or current is None or opening<=1 or current<=1 or line is None or selection not in {"OVER","UNDER"}:continue
            pid=item.get("eventParticipantId"); market="Общий тотал" if pid is None else f"ИТ {_ru_name(participant_names.get(pid,'команды'))}"; side="ТБ" if selection=="OVER" else "ТМ"; buckets.setdefault((market,scope,str(line),side),[]).append((opening,current))
    signals=[]
    for (market,scope,line,side),pairs in buckets.items():
        if len(pairs)<MIN_BOOKMAKERS:continue
        drops=[((o-c)/o)*100 for o,c in pairs]; consensus=sum(d>0 for d in drops)/len(drops); median_drop=statistics.median(drops)
        if median_drop<MIN_MEDIAN_DROP or consensus<MIN_CONSENSUS:continue
        signals.append(MovementSignal(market,SCOPE_LABELS.get(scope,scope),line,side,statistics.median(o for o,_ in pairs),statistics.median(c for _,c in pairs),median_drop,consensus,len(pairs),min(10.,median_drop*.325+consensus*3.5)))
    return sorted(signals,key=lambda s:s.score,reverse=True)[:MAX_SIGNALS_PER_MATCH]
def _telegram_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:return False
    try:r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",json={"chat_id":TELEGRAM_CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=20); return r.ok
    except requests.RequestException:return False
def _format(match,signals):
    start=match.kickoff.astimezone(MOSCOW).strftime("%H:%M"); lines=["🔥 <b>ПРЕДМАТЧЕВЫЙ ПРОГРУЗ</b>","",f"⚽ <b>{_ru_name(match.home)} — {_ru_name(match.away)}</b>",f"🏆 {_ru_league(match.league)}",f"🕒 Старт: <b>{start} МСК</b>",""]
    for s in signals:lines += [f"<b>{s.scope} · {s.market} {s.line} · {s.side}</b>",f"📉 {s.median_open:.2f} → {s.median_current:.2f} (-{s.median_drop:.1f}%)",f"🏦 Синхронно: {s.consensus*100:.0f}% ({s.bookmakers} букмекеров)",f"🔥 Давление рынка: {s.score:.1f}/10",""]
    lines.append("<i>Источник: Flashscore/LSApp · открытие линии → текущий коэффициент</i>"); return "\n".join(lines)
def _record_prematch(match,signals):
    for s in signals:
        key=f"prematch:{match.event_id}:{s.scope}:{s.market}:{s.line}:{s.side}"
        add_signal({"kind":"prematch","event_id":match.event_id,"home":_ru_name(match.home),"away":_ru_name(match.away),"league":_ru_league(match.league),"kickoff":match.kickoff.isoformat(),"scope":s.scope,"market":s.market,"line":float(s.line),"side":s.side,"opening":s.median_open,"current":s.median_current,"drop":s.median_drop,"consensus":s.consensus,"bookmakers":s.bookmakers,"market_pressure":s.score},key)
def main():
    sent=0
    for match in _discover_matches():
        entries=_fetch_event_odds(match.event_id); signals=_extract_signals(entries,match) if entries else []
        if signals and _telegram_send(_format(match,signals)):
            _record_prematch(match,signals); sent+=1
    logger.info("Signals sent: %d",sent); return 0
if __name__=="__main__": raise SystemExit(main())
