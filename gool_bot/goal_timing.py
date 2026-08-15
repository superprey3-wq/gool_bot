"""Optional league goal-timing context for GOOL AI.

Fetches public 15-minute league segment percentages from SoccerSTATS and caches them.
This is a fail-open auxiliary signal: network/parsing failures never block LIVE analysis.
"""
from __future__ import annotations
import json,re,time,logging
from pathlib import Path
import requests

logger=logging.getLogger("goal_timing")
CACHE=Path(__file__).with_name("goal_timing_cache.json")
TTL=12*3600
SEGMENTS=("0-15","16-30","31-45","46-60","61-75","76-90")

# SoccerSTATS public league slugs. Extend safely as leagues are encountered.
ALIASES={
    "england: premier league":"england","premier league":"england",
    "england: championship":"england2","championship":"england2",
    "spain: laliga":"spain","spain: la liga":"spain","la liga":"spain",
    "italy: serie a":"italy","serie a":"italy",
    "germany: bundesliga":"germany","bundesliga":"germany",
    "germany: 2. bundesliga":"germany2","2. bundesliga":"germany2",
    "france: ligue 1":"france","ligue 1":"france",
    "portugal: primeira liga":"portugal","primeira liga":"portugal",
    "netherlands: eredivisie":"netherlands","eredivisie":"netherlands",
    "belgium: pro league":"belgium","jupiler pro league":"belgium",
    "scotland: premiership":"scotland","scottish premiership":"scotland",
    "turkey: super lig":"turkey","super lig":"turkey",
    "austria: bundesliga":"austria",
    "switzerland: super league":"switzerland",
}

def _norm(s):
    s=str(s or "").lower().replace("–","-").replace("—","-")
    return re.sub(r"\s+"," ",s).strip()

def league_slug(league):
    n=_norm(league)
    if n in ALIASES:return ALIASES[n]
    for k,v in ALIASES.items():
        if k in n:return v
    return None

def _load():
    try:
        d=json.loads(CACHE.read_text("utf-8"));return d if isinstance(d,dict) else {}
    except Exception:return {}

def _save(d):
    try:CACHE.write_text(json.dumps(d,ensure_ascii=False,indent=2),"utf-8")
    except Exception as e:logger.warning("TIMING_CACHE_SAVE_FAILED %s",e)

def _parse(html):
    # Public page section: Min. | Goals | % goals, one row per 15-minute segment.
    text=re.sub(r"<[^>]+>"," ",html)
    text=text.replace("&nbsp;"," ").replace("&#39;","'")
    out={}
    for seg in SEGMENTS:
        # Match segment followed by a goal count and a percentage.
        m=re.search(rf"\b{re.escape(seg)}\b\s+(?:\d+\s+)?(\d{{1,2}}(?:\.\d+)?)%",text,re.I)
        if not m:
            m=re.search(rf"\b{re.escape(seg)}\b[\s\S]{{0,80}}?(\d{{1,2}}(?:\.\d+)?)%",text,re.I)
        if m:
            try:out[seg]=float(m.group(1))
            except:pass
    return out

def get_league_timing(league):
    slug=league_slug(league)
    if not slug:return None
    cache=_load();row=cache.get(slug) or {};now=time.time()
    if row.get("segments") and now-float(row.get("ts",0) or 0)<TTL:return row["segments"]
    try:
        r=requests.get(f"https://www.soccerstats.com/timing.asp?league={slug}",timeout=8,headers={"User-Agent":"Mozilla/5.0"})
        if r.ok:
            segs=_parse(r.text)
            if len(segs)>=4:
                cache[slug]={"ts":now,"segments":segs};_save(cache);return segs
    except Exception as e:logger.info("TIMING_FETCH_FAILED %s %s",slug,e)
    return row.get("segments") or None

def context(match,engine):
    segs=get_league_timing(getattr(match,"league","") or "")
    if not segs:return {"available":False,"segment":None,"pct":None,"bonus":0.0,"segments":{}}
    segment="31-45" if engine in {"first_half","ht_hunter","ht"} else "76-90" if engine in {"second_half","late_risk","risk"} else None
    pct=segs.get(segment) if segment else None
    # Conservative auxiliary bonus only. League timing never dominates live evidence.
    bonus=0.0
    if pct is not None:
        bonus=max(-4.0,min(8.0,(float(pct)-16.0)*0.8))
    return {"available":True,"segment":segment,"pct":pct,"bonus":round(bonus,1),"segments":segs}
