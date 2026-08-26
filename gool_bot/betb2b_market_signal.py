"""BetB2B/1xBet market context for GOOL cards.
Read-only: market data never creates/blocks/changes GOOL probability.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable,Optional
import logging,re,threading,time,requests
logger=logging.getLogger("betb2b_market_signal");BASE="https://1xbet.fi/service-api";HEADERS={"User-Agent":"Mozilla/5.0","Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9","Referer":"https://1xbet.fi/","Origin":"https://1xbet.fi"};_LOCK=threading.Lock();_POINTS={};_EVENT_MAP={};_MARKET_STATE={};_LAST_SAMPLE_TS=0.;_SAMPLE_MIN_SECONDS=45.
@dataclass(frozen=True)
class MarketPoint: ts:float;odds:float;line:Optional[float]=None;source:str="BETB2B"
@dataclass(frozen=True)
class MarketSignal: dot:str;delta_pp:float;fast:bool;direction:int
@dataclass
class MarketState:
 offered:bool=False;last_seen:float=0.;missing_since:Optional[float]=None;suspends:int=0;reopens:int=0;last_reopen_delta_pp:float=0.;last_odds:Optional[float]=None

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
 if a.line is not None and b.line is not None and a.line!=b.line:delta+=max(-2.,min(2.,(b.line-a.line)*2.))
 fast=abs(delta)>=4. and b.ts-a.ts<=300
 if abs(delta)>=4.:direction,dot=(1 if delta>0 else -1),"🟣"
 elif abs(delta)<1.5:direction,dot=0,"🟡"
 elif delta>0:direction,dot=1,"🟢"
 else:direction,dot=-1,"🔴"
 return MarketSignal(dot,round(delta,2),fast,direction)
def card_market_dot(signal):return "🟡" if signal is None else signal.dot
def source_cluster(source):
 s=(source or "").lower();return "BETB2B" if any(x in s for x in ("1xbet","melbet","betb2b")) else (source or "UNKNOWN").upper()
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
def _append(k,p):
 with _LOCK:
  xs=_POINTS.setdefault(k,[])
  if xs and xs[-1].odds==p.odds and xs[-1].line==p.line:return
  xs.append(p);_POINTS[k]=[x for x in xs[-120:] if x.ts>=p.ts-21600]
def _state(k,now,market):
 """Infer suspension only when an already-observed goal-total disappears from a valid detail payload.
 This deliberately does NOT treat HTTP/feed failure as suspension."""
 with _LOCK:
  st=_MARKET_STATE.setdefault(k,MarketState())
  if market:
   _,odd=market
   if not st.offered and st.missing_since is not None:
    st.reopens+=1
    if st.last_odds and implied_probability(st.last_odds) and implied_probability(odd):st.last_reopen_delta_pp=round((implied_probability(odd)-implied_probability(st.last_odds))*100,2)
    logger.info("BETB2B_MARKET_REOPEN key=%s gap=%.1fs delta_pp=%+.2f suspends=%d",k,now-st.missing_since,st.last_reopen_delta_pp,st.suspends)
   st.offered=True;st.last_seen=now;st.missing_since=None;st.last_odds=odd
  elif st.offered:
   st.offered=False;st.missing_since=now;st.suspends+=1;logger.info("BETB2B_MARKET_SUSPEND key=%s count=%d",k,st.suspends)
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
   market=_main_over(detail);_state(k,now,market)
   if market:
    line,odd=market;_append(k,MarketPoint(now,odd,line));sampled+=1
  except Exception as exc:logger.debug("BETB2B_GAME_FAIL %s %s",eid,exc)
 logger.info("BETB2B_LIVE_SAMPLE events=%d priced=%d",len(events),sampled);return sampled
def signal_for_match(home,away):
 k=_key(home,away)
 with _LOCK:pts=list(_POINTS.get(k) or []);st=_MARKET_STATE.get(k)
 sig=classify_market(pts,target_is_selection=True)
 # Repeated suspend + meaningful repricing upgrades the private lamp to purple.
 if st and st.suspends>=2 and abs(st.last_reopen_delta_pp)>=1.5:return MarketSignal("🟣",sig.delta_pp,True,sig.direction)
 return sig
def market_state_for_match(home,away):
 with _LOCK:return _MARKET_STATE.get(_key(home,away))
def dot_for_match(home,away):return card_market_dot(signal_for_match(home,away))
