"""BetB2B/1xBet market context for GOOL cards.

Read-only helper: market movement is supplementary information only and MUST NOT
create, block or change a GOOL signal probability. 1xBet/Melbet are treated as
one BETB2B source cluster.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, Optional
import logging,re,threading,time,requests
logger=logging.getLogger("betb2b_market_signal");BASE="https://1xbet.fi/service-api";HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9","Referer":"https://1xbet.fi/","Origin":"https://1xbet.fi"};_LOCK=threading.Lock();_POINTS={};_EVENT_MAP={};_LAST_SAMPLE_TS=0.;_SAMPLE_MIN_SECONDS=45.
@dataclass(frozen=True)
class MarketPoint: ts:float;odds:float;line:Optional[float]=None;source:str="BETB2B"
@dataclass(frozen=True)
class MarketSignal: dot:str;delta_pp:float;fast:bool;direction:int
def implied_probability(odds):
 try:x=float(odds)
 except (TypeError,ValueError):return None
 return 1./x if x>1 else None
def classify_market(points:Iterable[MarketPoint],*,target_is_selection=True):
 pts=sorted((p for p in points if implied_probability(p.odds) is not None),key=lambda p:p.ts)
 if len(pts)<2:return MarketSignal("🟡",0.,False,0)
 newest=pts[-1].ts;recent=[p for p in pts if p.ts>=newest-1800]
 if len(recent)>=2:pts=recent
 a,b=pts[0],pts[-1];delta=(implied_probability(b.odds)-implied_probability(a.odds))*100.
 if not target_is_selection:delta=-delta
 if a.line is not None and b.line is not None and a.line!=b.line:
  line_move=b.line-a.line
  if target_is_selection:delta+=max(-2.,min(2.,line_move*2.))
 fast=abs(delta)>=4. and (b.ts-a.ts)<=300
 # Purple is reserved for an exceptional/strong move regardless of direction.
 # Direction remains available internally for later analytics.
 if abs(delta)>=4.0:direction,dot=(1 if delta>0 else -1),"🟣"
 elif abs(delta)<1.5:direction,dot=0,"🟡"
 elif delta>0:direction,dot=1,"🟢"
 else:direction,dot=-1,"🔴"
 return MarketSignal(dot,round(delta,2),fast,direction)
def card_market_dot(signal):return "🟡" if signal is None else signal.dot
def source_cluster(source):
 s=(source or "").lower()
 return "BETB2B" if any(x in s for x in ("1xbet","melbet","betb2b")) else (source or "UNKNOWN").upper()
def _norm(name):return " ".join(re.sub(r"[^a-z0-9]+"," ",str(name or "").lower()).split())
def _key(home,away):return _norm(home)+"|"+_norm(away)
def _request(path,params):
 r=requests.get(BASE+path,params=params,headers=HEADERS,timeout=12)
 if r.status_code!=200:raise RuntimeError(f"HTTP {r.status_code}")
 return r.json().get("Value")
def _main_over(event):
 overs=[];unders={}
 for group in event.get("GE") or []:
  if int(group.get("G") or -1)!=4:continue
  for bucket in group.get("E") or []:
   for row in bucket or []:
    try:t=int(row.get("T"));line=float(row.get("P"));odd=float(row.get("C"))
    except (TypeError,ValueError):continue
    if t==9 and odd>1:overs.append(row)
    elif t==10 and odd>1:unders[line]=odd
 if not overs:return None
 preferred=[x for x in overs if int(x.get("CE") or 0)==1]
 if preferred:return float(preferred[0]["P"]),float(preferred[0]["C"])
 scored=[]
 for row in overs:
  line=float(row["P"]);odd=float(row["C"]);u=unders.get(line);scored.append((abs(odd-2.)+(abs(u-2.) if u else 3.),line,odd))
 _,line,odd=min(scored);return line,odd
def _append(key,point):
 with _LOCK:
  xs=_POINTS.setdefault(key,[])
  if xs and xs[-1].odds==point.odds and xs[-1].line==point.line:return
  xs.append(point);cutoff=point.ts-6*3600;_POINTS[key]=[p for p in xs[-120:] if p.ts>=cutoff]
def sample_live(force=False):
 global _LAST_SAMPLE_TS
 now=time.time()
 with _LOCK:
  if not force and now-_LAST_SAMPLE_TS<_SAMPLE_MIN_SECONDS:return 0
  _LAST_SAMPLE_TS=now
 try:events=_request("/LiveFeed/Get1x2_VZip",{"sports":1,"count":1000,"lng":"en","mode":4,"country":1,"getEmpty":"true"}) or []
 except Exception as exc:logger.warning("BETB2B_LIVE_FEED_FAIL %s",exc);return 0
 sampled=0
 for event in events:
  home,away,eid=event.get("O1"),event.get("O2"),event.get("I")
  if not home or not away or not eid:continue
  k=_key(home,away)
  with _LOCK:_EVENT_MAP[k]={"id":eid,"home":home,"away":away,"ts":now}
  try:
   detail=_request("/LiveFeed/GetGameZip",{"id":eid,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2})
   if not isinstance(detail,dict):continue
   market=_main_over(detail)
   if market:
    line,odd=market;_append(k,MarketPoint(now,odd,line));sampled+=1
  except Exception as exc:logger.debug("BETB2B_GAME_FAIL %s %s",eid,exc)
 logger.info("BETB2B_LIVE_SAMPLE events=%d priced=%d",len(events),sampled);return sampled
def signal_for_match(home,away):
 k=_key(home,away)
 with _LOCK:pts=list(_POINTS.get(k) or [])
 return classify_market(pts,target_is_selection=True)
def dot_for_match(home,away):return card_market_dot(signal_for_match(home,away))
