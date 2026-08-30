"""Shadow runtime for GOOL CORE V3 Goal Distribution.

Writes auditable JSONL decisions and logs OVER/UNDER/NO_BET for FT/1H/2H.  It
sends no Telegram messages until calibration proves the new policy is reliable.
"""
from __future__ import annotations
import json,logging,time
from pathlib import Path
from live_engine import fetch_stats,parse_stats,get_previous_values
from goal_distribution_v3 import evaluate
LOG=logging.getLogger("goal_distribution_v3")
AUDIT=Path("goal_distribution_v3_audit.jsonl")
STATE=Path("goal_distribution_v3_state.json")

def _load():
 try:d=json.loads(STATE.read_text("utf-8"));return d if isinstance(d,dict) else {}
 except Exception:return {}
def _save(d):
 cutoff=time.time()-12*3600;d={k:v for k,v in d.items() if float(v.get("ts",0) or 0)>=cutoff};STATE.write_text(json.dumps(d,ensure_ascii=False),"utf-8")
def _write(row):
 try:
  with AUDIT.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
 except Exception:LOG.exception("CORE_V3_AUDIT_FAIL")
def _emit(m,dec):
 row={"ts":time.time(),"event_id":str(m.event_id),"home":m.home,"away":m.away,"score":f"{m.home_score}:{m.away_score}",**dec.dict()};_write(row)
 LOG.info("CORE_V3_SHADOW event=%s period=%s minute=%d score=%s potential=%.1f threat=%.1f lambda=%.3f p10=%.1f p_any=%.1f p0=%.1f decision=%s line=%s prob=%.1f fair=%s",m.event_id,dec.period,dec.minute,row["score"],dec.potential,dec.threat,dec.lambda_remaining,dec.p_goal_10m,dec.p_any_goal,dec.p0,dec.direction,dec.line,dec.probability,dec.fair_odd)

def scan(live):
 state=_load();now=time.time();n=0
 for m in live:
  minute=int(getattr(m,"minute",0) or 0);eid=str(m.event_id);total=int(getattr(m,"home_score",0) or 0)+int(getattr(m,"away_score",0) or 0);margin=int(getattr(m,"home_score",0) or 0)-int(getattr(m,"away_score",0) or 0)
  # Capture the half-time total for correct SECOND_HALF market translation.
  s=state.setdefault(eid,{"ts":now});s["ts"]=now
  if bool(getattr(m,"is_halftime",False)) or 45<=minute<=47:s.setdefault("ht_total",total)
  body=fetch_stats(eid)
  if not body:continue
  stats=parse_stats(body)
  if not stats:continue
  prev=get_previous_values(eid,minute,8)
  # Full-time distribution is useful from the normal warmup until late match.
  if 10<=minute<=88 and not bool(getattr(m,"is_halftime",False)):
   dec=evaluate("FULL_TIME",minute,total,stats,prev,margin,0,94);_emit(m,dec);n+=1
  # First-half distribution: same score total because all current goals belong to 1H.
  if 10<=minute<=43 and not bool(getattr(m,"is_halftime",False)):
   dec=evaluate("FIRST_HALF",minute,total,stats,prev,margin,0,47);_emit(m,dec);n+=1
  # Second-half total requires the HT baseline; never guess it if unavailable.
  if 50<=minute<=88 and "ht_total" in s:
   second_goals=max(0,total-int(s["ht_total"]));dec=evaluate("SECOND_HALF",minute,second_goals,stats,prev,margin,45,94);_emit(m,dec);n+=1
 _save(state);LOG.info("CORE_V3_SHADOW_CYCLE matches=%d decisions=%d",len(live),n);return n

LOG.info("CORE V3 Goal Distribution shadow active | FT+1H+2H | OVER+UNDER+NO_BET | no Telegram delivery")
