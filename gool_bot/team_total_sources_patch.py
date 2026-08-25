"""Candidate-only standard team totals from Kambi/BetRivers.

Bovada is intentionally disabled. Adds only the next two actionable individual
Over lines for each team: current team goals +0.5 and +1.5. Asian quarter lines,
period/team corners and other props are excluded.
"""
from __future__ import annotations
import time
from collections import defaultdict,deque
import live_candidate_patch as lc
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

def _kambi(home,away):
 e=kam_find(home,away);out=[]
 if not e:return out
 data=kam_event(str(e.get("id")))
 for offer in data.get("betOffers") or []:
  tn=str((offer.get("betOfferType") or {}).get("name") or "");cr=str((offer.get("criterion") or {}).get("label") or "");text=f"{tn} {cr}";low=text.lower()
  if not ("total goals by" in low or "team total" in low):continue
  if any(x in low for x in ("asian","corner","card","booking","shot","1st half","first half","2nd half","second half")):continue
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
 vals=[x["odd"] for x in clean]
 return {"scope":"FULL_TIME","market_type":f"TEAM_TOTAL_{side}","selection":"OVER","team_side":side,"team_name":name,"line":float(line),"odd":max(vals),"source":"Kambi/BetRivers","source_prices":clean,"source_count":len(clean),"market_status":"SINGLE_SOURCE","source_spread_pct":0.0,"extra_market":f"TEAM_TOTAL_{side}"}

def _rows(m):
 try:allrows=_kambi(m.home,m.away)
 except Exception:allrows=[]
 out=[]
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
