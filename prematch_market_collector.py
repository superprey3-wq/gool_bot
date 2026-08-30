"""GOOL Monkey pre-match market collector.

Builds a market baseline before kickoff so PROGRUZ can compare live movement with
what happened in the hours leading into the match.  It intentionally writes to the
same SQLite odds store and uses the same Flashscore event_id as the live collector.

Current free pre-match source: Kambi/BetRivers public offering feed.  The collector
starts watching fixtures up to PREMATCH_HORIZON_HOURS before kickoff and keeps the
snapshots under the Flashscore event id, so the history remains continuous after the
live collector takes over.
"""
from __future__ import annotations
import json,logging,os,re,time,unicodedata
from difflib import SequenceMatcher
from datetime import datetime,timezone
from typing import Any
import requests
import market_store

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
LOG=logging.getLogger("prematch_market")
FSIGN=os.getenv("FLASHSCORE_FSIGN","SW9D1eZo")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
HORIZON=max(1.0,min(12.0,float(os.getenv("GOOL_PREMATCH_HORIZON_HOURS","6"))))
POLL=max(45,int(os.getenv("GOOL_PREMATCH_POLL_SECONDS","120")))
MAX_EVENTS=max(10,min(100,int(os.getenv("GOOL_PREMATCH_MAX_EVENTS","60"))))
OPERATOR=os.getenv("GOOL_KAMBI_OPERATOR","rsiusnj")
KAMBI_LIST=f"https://eu-offering-api.kambicdn.com/offering/v2018/{OPERATOR}/listView/football/all/all/all/matches.json?lang=en_US&market=US"
KAMBI_EVENT=f"https://eu-offering-api.kambicdn.com/offering/v2018/{OPERATOR}/betoffer/event/{{event_id}}.json?lang=en_US&market=US&includeParticipants=true"

def _get(url,timeout=15):return requests.get(url,headers={"User-Agent":UA,"Accept":"application/json, text/plain, */*","x-fsign":FSIGN,"Referer":"https://www.flashscore.com/"},timeout=timeout)
def _parse_feed(body:str):
 rows=[];cur={}
 for part in (body or "").split("¬"):
  if "÷" not in part:continue
  k,v=part.split("÷",1)
  if "~" in k:
   prefix,key=k.rsplit("~",1)
   if cur.get("AA"):rows.append(cur)
   cur={};k=key
  cur[k]=v
 if cur.get("AA"):rows.append(cur)
 return rows
def _fs_upcoming():
 now=time.time();end=now+HORIZON*3600;out={}
 for day in (0,1):
  url=f"https://local-global.flashscore.ninja/2/x/feed/f_1_{day}_3_en_1"
  try:r=_get(url);body=r.text if r.status_code==200 else ""
  except Exception as exc:LOG.info("PREMATCH_FS_FAIL day=%s err=%s",day,type(exc).__name__);continue
  for x in _parse_feed(body):
   if str(x.get("AB") or "")!="1":continue
   try:ts=float(x.get("AD") or 0)
   except Exception:continue
   if ts>10_000_000_000:ts/=1000
   if not (now-300<=ts<=end):continue
   eid=str(x.get("AA") or "")
   if not eid:continue
   out[eid]={"event_id":eid,"home":x.get("AE") or x.get("CX") or "","away":x.get("AF") or x.get("CX_2") or "","start_ts":ts,"league":x.get("ZA") or ""}
 return sorted(out.values(),key=lambda x:x["start_ts"])[:MAX_EVENTS]
def _norm(v):
 s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().lower();s=re.sub(r"\b(fc|afc|cf|sc|fk|sv|ac|as|eng|ita|ger|den|hun|esp|gre)\b"," ",s);s=re.sub(r"\b(women|woman|w)\b"," women ",s);return " ".join(re.sub(r"[^a-z0-9]+"," ",s).split())
def _sim(a,b):
 a,b=_norm(a),_norm(b)
 if not a or not b:return 0.0
 if a==b:return 1.0
 if a in b or b in a:return .92
 return SequenceMatcher(None,a,b).ratio()
def _kambi_events():
 try:
  r=_get(KAMBI_LIST);r.raise_for_status();wrappers=r.json().get("events") or []
 except Exception as exc:LOG.info("PREMATCH_KAMBI_LIST_FAIL %s",type(exc).__name__);return []
 out=[]
 for w in wrappers:
  e=w.get("event") or w;state=str(e.get("state") or "").upper()
  if e.get("homeName") and e.get("awayName") and state in {"","NOT_STARTED"}:out.append(e)
 return out
def _match(fs,krows):
 best=None
 for e in krows:
  h,a=str(e.get("homeName") or ""),str(e.get("awayName") or "")
  score=max((_sim(fs["home"],h)+_sim(fs["away"],a))/2,(_sim(fs["home"],a)+_sim(fs["away"],h))/2)
  if best is None or score>best[0]:best=(score,e)
 return best[1] if best and best[0]>=.78 else None
def _scope(criterion,type_name):
 t=f"{criterion} {type_name}".lower()
 if "1st half" in t or "first half" in t:return "FIRST_HALF"
 if "2nd half" in t or "second half" in t:return "SECOND_HALF"
 return "FULL_TIME"
def _rows(fs,ke):
 try:r=_get(KAMBI_EVENT.format(event_id=ke.get("id")));r.raise_for_status();data=r.json()
 except Exception:return []
 now=time.time();iso=datetime.now(timezone.utc).isoformat();out=[]
 for offer in data.get("betOffers") or []:
  tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");key=f"{tn} {cr}".lower()
  if not any(x in key for x in ("over/under","total goals")) or any(x in key for x in ("asian","team total","corner","card","shot","booking","player"," by ")):continue
  scope=_scope(cr,tn)
  for o in offer.get("outcomes") or []:
   if o.get("status")!="OPEN":continue
   label=str(o.get("label") or "").lower();typ=str(o.get("type") or "").upper();side="OVER" if ("over" in label or typ=="OT_OVER") else "UNDER" if ("under" in label or typ=="OT_UNDER") else ""
   try:odd=float(o.get("odds"))/1000.;line=float(o.get("line"))/1000.
   except Exception:continue
   if not side or odd<=1.01 or abs(line*2-round(line*2))>1e-9:continue
   out.append({"event_id":fs["event_id"],"home":fs["home"],"away":fs["away"],"score":"PRE","score_live":"PRE","minute":None,"status":"PREMATCH","start_ts":fs["start_ts"],"seconds_to_kickoff":max(0,int(fs["start_ts"]-now)),"bookmaker_id":200000,"bookmaker":"Kambi/BetRivers","market":"TOTAL","market_raw":"OVER_UNDER","scope":scope,"line":line,"side":side,"odd":odd,"opening":None,"timestamp":iso,"source":"KAMBI_PREMATCH"})
 return out
def cycle():
 fs=_fs_upcoming();ks=_kambi_events();records=[];matched=0
 for event in fs:
  ke=_match(event,ks)
  if not ke:continue
  rows=_rows(event,ke)
  if rows:matched+=1;records.extend(rows)
 if records:market_store.ingest(records,"prematch_kambi")
 LOG.info("PREMATCH_MARKET_CYCLE upcoming=%d kambi_events=%d matched=%d records=%d horizon=%.1fh",len(fs),len(ks),matched,len(records),HORIZON)
 return len(records)
def main():
 LOG.info("GOOL PREMATCH MARKET online horizon=%.1fh poll=%ss continuous_event_id=on",HORIZON,POLL)
 while True:
  try:cycle()
  except Exception:LOG.exception("PREMATCH_MARKET cycle failed; continuing")
  time.sleep(POLL)
if __name__=="__main__":main()
