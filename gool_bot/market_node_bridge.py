"""Bridge a lightweight remote market node into GOOL's private market lamp.

The remote node is a second-IP observer. It does not send Telegram. This module
polls its compact JSON snapshot and monkey-patches betb2b_market_signal so cards
can use a two-node consensus without changing GOOL signal eligibility.
"""
from __future__ import annotations
import logging,os,threading,time,requests
import betb2b_market_signal as bms

log=logging.getLogger("market_node_bridge")
URL=os.getenv("MARKET_NODE_URL","").strip().rstrip("/")
SECRET=os.getenv("MARKET_NODE_SECRET","").strip()
INTERVAL=max(10,int(os.getenv("MARKET_NODE_PULL_SECONDS","15")))
LOCK=threading.Lock();REMOTE={};LAST_OK=0.;LAST_ERROR=""
_ORIG_SIGNAL=bms.signal_for_match
_ORIG_DOT=bms.dot_for_match

def _key(home,away):return bms._key(home,away)
def _remote_signal(home,away):
 k=_key(home,away)
 with LOCK:row=dict(REMOTE.get(k) or {})
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
  d=(local.delta_pp+remote.delta_pp)/2
  dot="🟢" if local.direction>0 else "🔴"
  if abs(d)>=4:dot="🟣"
  return bms.MarketSignal(dot,round(d,2),local.fast or remote.fast,local.direction)
 if local.direction and remote.direction and local.direction!=remote.direction:
  return bms.MarketSignal("🟡",0.0,False,0)
 return remote if remote.direction else local

def dot_for_match(home,away):return bms.card_market_dot(signal_for_match(home,away))

def poll_once():
 global LAST_OK,LAST_ERROR
 if not URL:return 0
 headers={"Authorization":"Bearer "+SECRET} if SECRET else {}
 try:
  r=requests.get(URL+"/snapshot",headers=headers,timeout=10)
  if r.status_code==401:raise RuntimeError("401 unauthorized: MARKET_NODE_SECRET mismatch")
  r.raise_for_status();body=r.json();events=body.get("events") or {}
  if not isinstance(events,dict):raise RuntimeError("invalid events payload")
  with LOCK:
   REMOTE.clear();REMOTE.update(events)
  LAST_OK=time.time();LAST_ERROR="";age=max(0.,time.time()-float(body.get("ts") or time.time()))
  log.info("PROGRUZ_ONLINE events=%d age=%.1fs",len(events),age)
  return len(events)
 except Exception as exc:
  LAST_ERROR=f"{type(exc).__name__}: {exc}";log.warning("PROGRUZ_OFFLINE %s",LAST_ERROR);return 0

def health():return {"configured":bool(URL),"last_ok":LAST_OK,"last_error":LAST_ERROR,"events":len(REMOTE),"url":URL}

bms.signal_for_match=signal_for_match
bms.dot_for_match=dot_for_match
