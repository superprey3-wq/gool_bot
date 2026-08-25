"""Attach period-specific PREMATCH market context to auxiliary strategies.

Observation-first: market movement is recorded for analysis and explainability;
it does not gate FIRST_HALF_GOAL or SECOND_HALF_OVER15 eligibility.
"""
from __future__ import annotations
import logging
import multi_engine_runtime as rt
import prematch_market_service as pms

logger=logging.getLogger("period_prematch_market")
_orig_record=rt._record


def _txt(v): return str(v or "").upper().replace("-","_").replace(" ","_")

def _period(scope):
 s=_txt(scope)
 if any(x in s for x in ("FIRST_HALF","1ST_HALF","1H","HALF_1")): return "1T"
 if any(x in s for x in ("SECOND_HALF","2ND_HALF","2H","HALF_2")): return "2T"
 return "FT"

def _kind(q):
 s=" ".join(_txt(q.get(k)) for k in ("betting_type","market","name","bettingType","selection","label"))
 if "OVER_UNDER" in s or "TOTAL" in s: return "TOTAL"
 if "HOME_DRAW_AWAY" in s or "1X2" in s or "MATCH_WINNER" in s: return "1X2"
 if "BTTS" in s or "BOTH_TEAMS" in s: return "BTTS"
 if "HANDICAP" in s: return "HANDICAP"
 return "OTHER"

def _num(v):
 try:return float(v)
 except:return None

def _context(event_id, target):
 try:ctx=pms.get_prematch_context(str(event_id)) or {}
 except Exception:return {}
 snaps=ctx.get("snapshots") or []
 if not snaps:return {}
 first=snaps[0]; last=ctx.get("final_prematch") or snaps[-1]
 def quotes(s): return (s.get("markets") or s.get("quotes") or []) if isinstance(s,dict) else []
 fq=quotes(first); lq=quotes(last)
 rows=[]
 for q in lq:
  if not isinstance(q,dict) or _period(q.get("betting_scope") or q.get("scope"))!=target:continue
  kind=_kind(q); cur=_num(q.get("value") or q.get("current") or q.get("odd")); opening=_num(q.get("opening"))
  if opening is None:
   # best-effort match against first snapshot
   for x in fq:
    if isinstance(x,dict) and _period(x.get("betting_scope") or x.get("scope"))==target and _kind(x)==kind and str(x.get("line"))==str(q.get("line")) and str(x.get("selection") or x.get("label"))==str(q.get("selection") or q.get("label")):
     opening=_num(x.get("value") or x.get("current") or x.get("odd"));break
  move_pp=None
  if opening and cur and opening>1 and cur>1:move_pp=round((100/cur)-(100/opening),2)
  rows.append({"kind":kind,"line":q.get("line"),"selection":q.get("selection") or q.get("label"),"opening":opening,"current":cur,"move_implied_pp":move_pp,"bookmaker":q.get("bookmaker") or q.get("source")})
 rows=sorted(rows,key=lambda r:abs(r.get("move_implied_pp") or 0),reverse=True)
 return {"period":target,"snapshots":len(snaps),"markets":rows[:24],"top_moves":rows[:6],"observation_only":True}

def _record(match,engine,score,d,market):
 target="1T" if engine==rt.FIRST_HALF_GOAL else "2T"
 pc=_context(match.event_id,target)
 if pc:
  d=dict(d or {});d["_prematch_period_market"]=pc
  logger.info("PERIOD_PREMATCH %s %s snapshots=%d markets=%d",target,match.event_id,pc.get("snapshots",0),len(pc.get("markets") or []))
 return _orig_record(match,engine,score,d,market)

rt._record=_record
