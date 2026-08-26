"""Bridge a lightweight remote market node into GOOL's private market lamp."""
from __future__ import annotations
import logging,os,threading,time,requests
from difflib import SequenceMatcher
import betb2b_market_signal as bms

log=logging.getLogger("market_node_bridge")
URL=os.getenv("MARKET_NODE_URL","").strip().rstrip("/")
SECRET=os.getenv("MARKET_NODE_SECRET","").strip()
INTERVAL=max(10,int(os.getenv("MARKET_NODE_PULL_SECONDS","15")))
LOCK=threading.Lock();REMOTE={};LAST_OK=0.;LAST_ERROR=""
_ORIG_SIGNAL=bms.signal_for_match;_ORIG_DOT=bms.dot_for_match

def _key(home,away):return bms._key(home,away)
def _sim(a,b):
 a=bms._norm(a);b=bms._norm(b)
 if not a or not b:return 0.0
 if a==b:return 1.0
 if a in b or b in a:return .94
 return SequenceMatcher(None,a,b).ratio()
def _lookup_remote(home,away):
 k=_key(home,away)
 with LOCK:
  exact=REMOTE.get(k)
  if exact:return k,dict(exact),"exact",1.0
  items=list(REMOTE.items())
 best=None;best_score=0.0
 for rk,row in items:
  rh=row.get("home") or "";ra=row.get("away") or "";hs=_sim(home,rh);as_=_sim(away,ra);score=(hs+as_)/2.0
  if min(hs,as_)<0.66 or score<0.78:continue
  if score>best_score:best=(rk,dict(row));best_score=score
 if best:return best[0],best[1],"fuzzy",best_score
 return k,{},"none",0.0
def _remote_signal(home,away):
 _,row,_,_=_lookup_remote(home,away);declared=str(row.get("market_dot") or "")
 try:declared_delta=float(row.get("market_delta_pp",0) or 0)
 except Exception:declared_delta=0.0
 if declared in ("🟢","🔴","🟣","🟡") and row.get("best_market"):
  direction=1 if declared_delta>0 else -1 if declared_delta<0 else 0
  return bms.MarketSignal(declared,round(declared_delta,2),declared=="🟣",direction)
 pts=[]
 for x in row.get("points") or []:
  try:pts.append(bms.MarketPoint(float(x[0]),float(x[1]),float(x[2]) if x[2] is not None else None,"BETB2B_NODE"))
  except Exception:continue
 sig=bms.classify_market(pts,target_is_selection=True)
 strong_suspend=int(row.get("suspends",0) or 0)>=2 and abs(float(row.get("last_reopen_delta_pp",0) or 0))>=1.5
 if strong_suspend:return bms.MarketSignal("🟣",sig.delta_pp,True,sig.direction)
 return sig

def signal_for_match(home,away):
 local=_ORIG_SIGNAL(home,away);remote=_remote_signal(home,away)
 if remote.delta_pp==0 and remote.dot=="🟡":return local
 if local.dot=="🟣" or remote.dot=="🟣":
  chosen=remote if abs(remote.delta_pp)>=abs(local.delta_pp) else local
  return bms.MarketSignal("🟣",chosen.delta_pp,True,chosen.direction)
 if local.direction and remote.direction and local.direction==remote.direction:
  d=(local.delta_pp+remote.delta_pp)/2;dot="🟢" if local.direction>0 else "🔴"
  if abs(d)>=4:dot="🟣"
  return bms.MarketSignal(dot,round(d,2),local.fast or remote.fast,local.direction)
 if local.direction and remote.direction and local.direction!=remote.direction:return bms.MarketSignal("🟡",0.0,False,0)
 return remote if remote.direction else local

def dot_for_match(home,away):return bms.card_market_dot(signal_for_match(home,away))
def diagnostic_for_match(home,away):
 rk,row,mode,similarity=_lookup_remote(home,away);remote=_remote_signal(home,away);local=_ORIG_SIGNAL(home,away);final=signal_for_match(home,away)
 return {"match_mode":mode,"similarity":round(similarity,3),"remote_key":rk if row else "","remote_points":len(row.get("points") or []),"remote_market":row.get("best_market") or "","remote_strength":row.get("market_strength",0),"remote_start_odds":row.get("best_market_start_odds"),"remote_last_odds":row.get("best_market_last_odds") or row.get("last_odds"),"top_markets":list(row.get("top_markets") or []),"local_dot":local.dot,"local_delta":local.delta_pp,"remote_dot":remote.dot,"remote_delta":remote.delta_pp,"final_dot":final.dot,"final_delta":final.delta_pp}

def poll_once():
 global LAST_OK,LAST_ERROR
 if not URL:return 0
 headers={"Authorization":"Bearer "+SECRET} if SECRET else {}
 try:
  r=requests.get(URL+"/snapshot",headers=headers,timeout=10)
  if r.status_code==401:raise RuntimeError("401 unauthorized: MARKET_NODE_SECRET mismatch")
  r.raise_for_status();body=r.json();events=body.get("events") or {}
  if not isinstance(events,dict):raise RuntimeError("invalid events payload")
  with LOCK:REMOTE.clear();REMOTE.update(events)
  LAST_OK=time.time();LAST_ERROR="";age=max(0.,time.time()-float(body.get("ts") or time.time()))
  log.info("PROGRUZ_ONLINE events=%d age=%.1fs strongest=%s",len(events),age,bool(body.get("strongest_market_snapshot")));return len(events)
 except Exception as exc:
  LAST_ERROR=f"{type(exc).__name__}: {exc}";log.warning("PROGRUZ_OFFLINE %s",LAST_ERROR);return 0

def health():return {"configured":bool(URL),"last_ok":LAST_OK,"last_error":LAST_ERROR,"events":len(REMOTE),"url":URL}

bms.signal_for_match=signal_for_match;bms.dot_for_match=dot_for_match
