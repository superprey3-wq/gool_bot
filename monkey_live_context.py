"""Unified Flashscore live truth for Monkey PROGRUZ and BEST BET.

Uses the same production live_engine as GOOL main. One JSON snapshot is the single
source of truth for score, absolute minute, status, parsed live stats and rolling
8-minute goal pressure/momentum.
"""
from __future__ import annotations
import asyncio,json,logging,os,sys,time
from dataclasses import asdict
from pathlib import Path
HOME=Path(os.getenv("GOOL_HOME","/home/container"));RUNTIME=HOME/"bestbet_runtime"/"gool_bot";STATE=Path(os.getenv("GOOL_MONKEY_LIVE_CONTEXT",str(HOME/"monkey_live_context.json")));POLL=max(12,int(os.getenv("GOOL_MONKEY_LIVE_POLL_SECONDS","20")))
os.environ.setdefault("LIVE_STATE_FILE",str(HOME/"monkey_live_stats_history.json"))
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");log=logging.getLogger("monkey_live_context")
from live_engine import discover_live_matches,fetch_stats,parse_stats,calculate_goal_pressure,get_previous_values,save_snapshot,StatsSnapshot

def _pair(v):
 try:return [float(v[0]),float(v[1])]
 except Exception:return [0.0,0.0]
def _stats_for(eid):
 try:
  body=fetch_stats(str(eid));d=parse_stats(body) if body else {}
  return d if isinstance(d,dict) else {}
 except Exception as exc:
  log.info("MONKEY_LIVE_STATS_FAIL event=%s err=%s",eid,type(exc).__name__);return {}
def _pressure(m,eid,stats):
 if not stats:return {}
 try:
  minute=int(getattr(m,"minute",0) or 0);prev=get_previous_values(str(eid),minute,lookback_minutes=8) or {}
  p=calculate_goal_pressure(m,stats,prev)
  save_snapshot(str(eid),StatsSnapshot(ts=int(time.time()),minute=minute,values=stats))
  return asdict(p)
 except Exception as exc:
  log.info("MONKEY_PRESSURE_FAIL event=%s err=%s",eid,type(exc).__name__);return {}
def _row(m,stats,pressure):
 clean={k:_pair(v) for k,v in stats.items()}
 return {"event_id":str(getattr(m,"event_id","")),"home":str(getattr(m,"home","") or ""),"away":str(getattr(m,"away","") or ""),"home_score":int(getattr(m,"home_score",0) or 0),"away_score":int(getattr(m,"away_score",0) or 0),"score":f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}","minute":int(getattr(m,"minute",0) or 0),"status":str(getattr(m,"status","") or "LIVE"),"league":str(getattr(m,"league","") or ""),"is_halftime":bool(getattr(m,"is_halftime",False)),"stats":clean,"pressure":pressure,"ts":int(time.time())}
def _write(rows):
 payload={"ts":int(time.time()),"source":"production_live_engine_flashscore","events":{r["event_id"]:r for r in rows if r.get("event_id")}}
 tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8");tmp.replace(STATE)
async def cycle():
 live=await discover_live_matches();rows=[]
 for m in live:
  eid=str(getattr(m,"event_id","") or "")
  if not eid:continue
  stats=await asyncio.to_thread(_stats_for,eid);pressure=_pressure(m,eid,stats);r=_row(m,stats,pressure);rows.append(r)
  log.info("MONKEY_LIVE event=%s score=%s minute=%s status=%s stats=%d pressure=%s momentum=%s",eid,r["score"],r["minute"],r["status"],len(stats),pressure.get("score"),pressure.get("momentum"))
 _write(rows);log.info("MONKEY_LIVE_COMMIT events=%d state=%s",len(rows),STATE)
async def main():
 log.info("GOOL MONKEY LIVE TRUTH production Flashscore engine + rolling pressure poll=%ss",POLL)
 while True:
  started=time.monotonic()
  try:await cycle()
  except Exception:log.exception("MONKEY_LIVE cycle failed")
  await asyncio.sleep(max(2.0,POLL-(time.monotonic()-started)))
if __name__=="__main__":asyncio.run(main())
