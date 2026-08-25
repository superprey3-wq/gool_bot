"""Full-world LIVE discovery from the lightweight Flashscore master feed."""
from __future__ import annotations
import logging,time
from typing import Any
from live_engine import LiveMatch,_feed
logger=logging.getLogger("live_feed_discovery")
LIVE_COARSE_STATUS="2";FIRST_HALF_STATUS="12";SECOND_HALF_STATUS="13";HALFTIME_STATUS="38"
def _fields(raw:str)->dict[str,str]:
 out={}
 for token in raw.split("¬"):
  if "÷" in token:
   k,v=token.split("÷",1)
   if k and k not in out:out[k]=v
 return out
def _as_int(value:Any,default:int=0)->int:
 try:return int(float(str(value)))
 except (TypeError,ValueError):return default
def _minute(fields:dict[str,str],now:int)->tuple[int,bool]:
 ac=fields.get("AC","");ao=_as_int(fields.get("AO"));ad=_as_int(fields.get("AD"))
 if ac==HALFTIME_STATUS:return 45,True
 if ac==FIRST_HALF_STATUS:
  base=ao or ad;elapsed=max(0,now-base) if base else 0;return max(1,min(45,elapsed//60+1)),False
 if ac==SECOND_HALF_STATUS:
  base=ao or ad;elapsed=max(0,now-base) if base else 0;return max(46,min(90,45+elapsed//60+1)),False
 if ao:
  elapsed=max(0,now-ao)//60+1
  if ac=="6":return max(91,min(130,90+elapsed)),False
 if ad:
  elapsed=max(1,(now-ad)//60+1)
  if elapsed>60:elapsed-=15
  return max(1,min(130,elapsed)),False
 return 1,False
def parse_master_live(body:str)->list[LiveMatch]:
 now=int(time.time());matches=[];league=""
 for chunk in (body or "").split("~"):
  if not chunk:continue
  if chunk.startswith("ZA÷"):
   league=_fields(chunk).get("ZA","").strip();continue
  if not chunk.startswith("AA÷"):continue
  event_id,sep,rest=chunk[3:].partition("¬")
  if not sep or len(event_id)!=8 or not event_id.isalnum():continue
  f=_fields(rest)
  if f.get("AB")!=LIVE_COARSE_STATUS:continue
  home=(f.get("AE") or f.get("CX") or "").strip();away=(f.get("AF") or "").strip()
  if not home or not away:continue
  hs=_as_int(f.get("AG"),_as_int(f.get("AT")));as_=_as_int(f.get("AH"),_as_int(f.get("AU")));minute,is_ht=_minute(f,now);ac=f.get("AC","")
  matches.append(LiveMatch(event_id,minute,home,away,hs,as_,f"feed AB=2 AC={ac}",league,is_ht))
 return list({m.event_id:m for m in matches}.values())
async def discover_live_matches()->list[LiveMatch]:
 body=_feed("f_1_0_0_en_1")
 if not body:
  logger.warning("Flashscore master feed unavailable; no browser fallback on lightweight VPS")
  return []
 matches=parse_master_live(body)
 if matches:logger.info("MASTER-FEED LIVE: %d матчей (AB=2)",len(matches))
 else:logger.warning("Master feed loaded but no AB=2 events parsed")
 return matches
