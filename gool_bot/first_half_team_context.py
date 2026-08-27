"""Cached pre-match/team context for the FIRST_HALF_GOAL engine.

Uses only observable data:
- Flashscore/LSApp opening 1X2 prices as a favourite/underdog proxy;
- recent-match event timelines to measure first-half goal/scoring/conceding rates;
- venue split and H2H first-half goal rate.

The context is deliberately a secondary filter. LIVE chance quality and pressure
remain mandatory; historical/odds context can strengthen or veto marginal cases.
"""
from __future__ import annotations
import json,re,time,statistics
from pathlib import Path
from typing import Any
import requests
from live_engine import fetch_summary,parse_goal_timeline
from match_history import PastMatch,fetch_match_history

CACHE=Path(__file__).with_name("first_half_team_context_cache.json")
TTL=6*3600
ODDS_URL="https://global.ds.lsapp.eu/odds/pq_graphql"
HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json, text/plain, */*","Referer":"https://www.flashscore.com/"}

def _norm(s:str)->str:return " ".join(str(s or "").replace("*","").lower().split())
def _load():
 try:d=json.loads(CACHE.read_text("utf-8"));return d if isinstance(d,dict) else {}
 except:return {}
def _save(d):
 try:CACHE.write_text(json.dumps(d,ensure_ascii=False),"utf-8")
 except Exception:pass

def _minute(item:str)->int|None:
 m=re.match(r"\s*(\d{1,3})",str(item or ""))
 if not m:return None
 try:return int(m.group(1))
 except ValueError:return None

def _fh_timeline(row:PastMatch)->list[str]:
 if not row.event_id:return []
 return [g for g in parse_goal_timeline(fetch_summary(row.event_id)) if (_minute(g) or 999)<=45]

def _team_stats(rows:list[PastMatch],team:str,venue:str|None=None)->dict[str,float]:
 tn=_norm(team);usable=[]
 for r in rows:
  is_home=_norm(r.home)==tn;is_away=_norm(r.away)==tn
  if not (is_home or is_away):continue
  if venue=="home" and not is_home:continue
  if venue=="away" and not is_away:continue
  goals=_fh_timeline(r)
  if not r.event_id:continue
  team_scored=any(("хозяева" in g and is_home) or ("гости" in g and is_away) for g in goals)
  team_conceded=any(("гости" in g and is_home) or ("хозяева" in g and is_away) for g in goals)
  usable.append((bool(goals),team_scored,team_conceded))
 n=len(usable)
 if not n:return {"n":0,"fh_goal":0.0,"fh_scored":0.0,"fh_conceded":0.0}
 return {"n":n,"fh_goal":sum(x[0] for x in usable)/n,"fh_scored":sum(x[1] for x in usable)/n,"fh_conceded":sum(x[2] for x in usable)/n}

def _h2h_stats(rows:list[PastMatch])->dict[str,float]:
 usable=[]
 for r in rows:
  if not r.event_id:continue
  goals=_fh_timeline(r);usable.append(bool(goals))
 n=len(usable)
 return {"n":n,"fh_goal":sum(usable)/n if n else 0.0}

def _favourite(event_id:str)->dict[str,Any]:
 params={"_hash":"oce","eventId":event_id,"projectId":"5","geoIpCode":"US","geoIpSubdivisionCode":"USCA"}
 try:r=requests.get(ODDS_URL,params=params,headers=HEADERS,timeout=12);r.raise_for_status();payload=r.json()
 except Exception:return {"side":"unknown","home_odd":None,"draw_odd":None,"away_odd":None,"gap":0.0}
 entries=payload.get("data",{}).get("findOddsByEventId",{}).get("odds",[]) or []
 hs=[];ds=[];aws=[]
 for entry in entries:
  if str(entry.get("bettingType") or "")!="HOME_DRAW_AWAY" or str(entry.get("bettingScope") or "FULL_TIME")!="FULL_TIME":continue
  for item in entry.get("odds") or []:
   if not isinstance(item,dict):continue
   sel=str(item.get("selection") or "").upper();v=item.get("opening") if item.get("opening") is not None else item.get("value")
   try:v=float(v)
   except (TypeError,ValueError):continue
   if v<=1:continue
   if sel in {"HOME","1"}:hs.append(v)
   elif sel in {"DRAW","X"}:ds.append(v)
   elif sel in {"AWAY","2"}:aws.append(v)
 if not hs or not aws:return {"side":"unknown","home_odd":None,"draw_odd":None,"away_odd":None,"gap":0.0}
 ho=statistics.median(hs);ao=statistics.median(aws);do=statistics.median(ds) if ds else None
 hp=1/ho;ap=1/ao;dp=1/do if do else 0.0;den=hp+ap+dp
 hp,ap=(hp/den,ap/den) if den else (0.0,0.0);gap=abs(hp-ap)
 side="balanced" if gap<.10 else ("home" if hp>ap else "away")
 return {"side":side,"home_odd":round(ho,2),"draw_odd":round(do,2) if do else None,"away_odd":round(ao,2),"home_prob":round(hp,3),"away_prob":round(ap,3),"gap":round(gap,3)}

def context(event_id:str,home:str,away:str)->dict[str,Any]:
 cache=_load();row=cache.get(str(event_id)) or {};now=time.time()
 if row and now-float(row.get("ts",0) or 0)<TTL:return row.get("data") or {}
 hist=fetch_match_history(event_id,home,away,limit=6)
 home_all=_team_stats(hist.home_recent,home);away_all=_team_stats(hist.away_recent,away)
 home_venue=_team_stats(hist.home_recent,home,"home");away_venue=_team_stats(hist.away_recent,away,"away")
 h2h=_h2h_stats(hist.h2h);fav=_favourite(event_id)
 rates=[x["fh_goal"] for x in (home_all,away_all) if x["n"]>=3]
 combined=sum(rates)/len(rates) if rates else None
 bonus=0.0;veto=False;reasons=[]
 sample=home_all["n"]+away_all["n"]
 if combined is not None:
  if combined>=.75:bonus+=4;reasons.append("recent FH-goal rate high")
  elif combined>=.62:bonus+=2
  elif combined<.45 and sample>=8:bonus-=7;veto=True;reasons.append("recent FH-goal rate low")
 side=fav.get("side")
 if side=="home" and home_all["n"]>=3:
  if home_all["fh_scored"]>=.55:bonus+=2
  if home_venue["n"]>=2 and home_venue["fh_scored"]>=.5:bonus+=1.5
 elif side=="away" and away_all["n"]>=3:
  if away_all["fh_scored"]>=.55:bonus+=2
  if away_venue["n"]>=2 and away_venue["fh_scored"]>=.5:bonus+=1.5
 if h2h["n"]>=3 and h2h["fh_goal"]>=.67:bonus+=1.5
 if float(fav.get("gap",0) or 0)>=.18:bonus+=1
 data={"favourite":fav,"home_recent":home_all,"away_recent":away_all,"home_at_home":home_venue,"away_away":away_venue,"h2h":h2h,"combined_fh_goal_rate":round(combined,3) if combined is not None else None,"sample":sample,"bonus":round(max(-8,min(8,bonus)),1),"veto":veto,"reasons":reasons}
 cache[str(event_id)]={"ts":now,"data":data};_save(cache);return data
