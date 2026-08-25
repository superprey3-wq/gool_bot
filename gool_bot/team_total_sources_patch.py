"""Candidate-only standard team totals from Bovada + Kambi.

Adds only the next two actionable individual Over lines for each team:
current team goals +0.5 and +1.5. Asian quarter lines, period/team corners and
other props are excluded. This module never creates a GOOL candidate by itself.
"""
from __future__ import annotations
import re,time
from collections import defaultdict,deque
import live_candidate_patch as lc
from bovada_live_odds import _find_event as bov_find,_ratio as bov_ratio
from kambi_live_odds import _find_event as kam_find,_event_data as kam_event,_sim as kam_sim

_orig_market=lc._market
_HISTORY=defaultdict(lambda:deque(maxlen=4));_TTL=45*60

def _std(line):
 try:return abs(float(line)*2-round(float(line)*2))<1e-9
 except:return False

def _track(key,odd):
 now=time.time();q=_HISTORY[key]
 while q and now-q[0][0]>_TTL:q.popleft()
 if not q or abs(float(q[-1][1])-float(odd))>1e-6 or now-q[-1][0]>=20:q.append((now,float(odd)))
 if len(q)<2:return {"direction":"flat","from":round(float(odd),3),"to":round(float(odd),3),"drop_pct":0.0}
 old,new=float(q[0][1]),float(q[-1][1]);drop=(old-new)/old*100 if old>1 else 0
 return {"direction":"toward" if drop>.5 else "against" if drop<-.5 else "flat","from":round(old,3),"to":round(new,3),"drop_pct":round(drop,2)}

def _side(name,home,away,sim):
 hs,as_=sim(name,home),sim(name,away)
 if max(hs,as_)<.62:return None
 return "HOME" if hs>=as_ else "AWAY"

def _bovada(home,away):
 e=bov_find(home,away);out=[]
 if not e:return out
 for group in e.get("displayGroups") or []:
  gl=str(group.get("description") or "").lower()
  if any(x in gl for x in ("corner","card","booking")):continue
  for market in group.get("markets") or []:
   if not isinstance(market,dict) or str(market.get("status") or "O")!="O":continue
   desc=str(market.get("description") or "").strip();low=desc.lower()
   if "total" not in low or "asian" in low:continue
   m=re.search(r"(?:total goals o/u|team total)\s*[-:]\s*(.+)$",desc,re.I)
   if not m:continue
   team=m.group(1).strip();side=_side(team,home,away,bov_ratio)
   if not side:continue
   for o in market.get("outcomes") or []:
    if str(o.get("status") or "O")!="O" or not str(o.get("description") or "").lower().startswith("over"):continue
    p=o.get("price") or {}
    try:line=float(p.get("handicap"));odd=float(p.get("decimal"))
    except (TypeError,ValueError):continue
    if odd>1.001 and _std(line):out.append({"team_side":side,"team_name":home if side=="HOME" else away,"line":line,"odd":odd,"source":"Bovada"})
 return out

def _kambi(home,away):
 e=kam_find(home,away);out=[]
 if not e:return out
 data=kam_event(str(e.get("id")))
 for offer in data.get("betOffers") or []:
  tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");text=f"{tn} {cr}";low=text.lower()
  if not ("total goals by" in low or "team total" in low):continue
  if any(x in low for x in ("asian","corner","card","booking","shot","1st half","first half","2nd half","second half")):continue
  # Identify the referenced team from criterion/type text.
  side="HOME" if kam_sim(text,home)>=kam_sim(text,away) else "AWAY"
  if max(kam_sim(text,home),kam_sim(text,away))<.28:continue
  for o in offer.get("outcomes") or []:
   if o.get("status")!="OPEN":continue
   label=str(o.get("label") or "").lower();typ=str(o.get("type") or "")
   if "over" not in label and typ!="OT_OVER":continue
   try:line=float(o.get("line"))/1000;odd=float(o.get("odds"))/1000
   except (TypeError,ValueError):continue
   if odd>1.001 and _std(line):out.append({"team_side":side,"team_name":home if side=="HOME" else away,"line":line,"odd":odd,"source":"Kambi/BetRivers"})
 return out

def _pack(event_id,side,name,line,rows):
 clean=[]
 for r in rows:
  try:odd=float(r["odd"])
  except:continue
  clean.append({"source":r["source"],"odd":odd,"movement":_track(f"{event_id}|TEAM_TOTAL|{side}|{line}|{r['source']}",odd)})
 if not clean:return None
 vals=[x["odd"] for x in clean];spread=(max(vals)-min(vals))/min(vals)*100 if len(vals)>=2 and min(vals)>0 else 0;toward=sum(x["movement"]["direction"]=="toward" for x in clean)
 status="STEAM" if len(clean)>=2 and toward>=2 else "CONFIRMED" if len(clean)>=2 and spread<=15 else "DISAGREE" if len(clean)>=2 else "EARLY"
 return {"scope":"FULL_TIME","market_type":f"TEAM_TOTAL_{side}","selection":"OVER","team_side":side,"team_name":name,"line":float(line),"odd":max(vals),"source":"MULTI_SOURCE","source_prices":clean,"source_count":len(clean),"market_status":status,"source_spread_pct":round(spread,2),"extra_market":f"TEAM_TOTAL_{side}"}

def _rows(m):
 try:b=_bovada(m.home,m.away)
 except Exception:b=[]
 try:k=_kambi(m.home,m.away)
 except Exception:k=[]
 allrows=b+k;out=[]
 for side,name,goals in (("HOME",m.home,int(m.home_score or 0)),("AWAY",m.away,int(m.away_score or 0))):
  for line in (goals+.5,goals+1.5):
   same=[r for r in allrows if r.get("team_side")==side and abs(float(r.get("line",-99))-line)<1e-9]
   p=_pack(m.event_id,side,name,line,same)
   if p:out.append(p)
 return out

def _market(entries,m,p):
 recs,market=_orig_market(entries,m,p)
 try:rows=_rows(m)
 except Exception:rows=[]
 if rows:
  recs.extend(rows);market["team_totals"]=rows
 return recs,market

lc._market=_market
