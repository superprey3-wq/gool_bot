"""Unified Flashscore live truth for Monkey PROGRUZ and BEST BET.

Uses the same production live_engine as GOOL main. One JSON snapshot becomes the
single source of truth for event score, absolute minute, status and parsed live stats.
"""
from __future__ import annotations
import asyncio,json,logging,os,sys,time
from pathlib import Path
HOME=Path(os.getenv("GOOL_HOME","/home/container"));RUNTIME=HOME/"bestbet_runtime"/"gool_bot";STATE=Path(os.getenv("GOOL_MONKEY_LIVE_CONTEXT",str(HOME/"monkey_live_context.json")));POLL=max(12,int(os.getenv("GOOL_MONKEY_LIVE_POLL_SECONDS","20")))
if str(RUNTIME) not in sys.path:sys.path.insert(0,str(RUNTIME))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");log=logging.getLogger("monkey_live_context")
from live_engine import discover_live_matches,fetch_stats,parse_stats

def _pair(v):
 try:return [float(v[0]),float(v[1])]
 except Exception:return [0.0,0.0]
def _stats_for(eid):
 try:
  body=fetch_stats(str(eid));d=parse_stats(body) if body else {}
  return {k:_pair(v) for k,v in d.items()} if isinstance(d,dict) else {}
 except Exception as exc:
  log.info("MONKEY_LIVE_STATS_FAIL event=%s err=%s",eid,type(exc).__name__);return {}
def _row(m,stats):
 return {"event_id":str(getattr(m,"event_id","")),"home":str(getattr(m,"home","") or ""),"away":str(getattr(m,"away","") or ""),"home_score":int(getattr(m,"home_score",0) or 0),"away_score":int(getattr(m,"away_score",0) or 0),"score":f"{int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}","minute":int(getattr(m,"minute",0) or 0),"status":str(getattr(m,"status","") or "LIVE"),"league":str(getattr(m,"league","") or ""),"is_halftime":bool(getattr(m,"is_halftime",False)),"stats":stats,"ts":int(time.time())}
def _write(rows):
 payload={"ts":int(time.time()),"source":"production_live_engine_flashscore","events":{r["event_id"]:r for r in rows if r.get("event_id")}}
 tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8");tmp.replace(STATE)
async def cycle():
 live=await discover_live_matches();rows=[]
 for m in live:
  eid=str(getattr(m,"event_id","") or "")
  if not eid:continue
  stats=await asyncio.to_thread(_stats_for,eid);r=_row(m,stats);rows.append(r)
  log.info("MONKEY_LIVE event=%s score=%s minute=%s status=%s stats=%d",eid,r["score"],r["minute"],r["status"],len(stats))
 _write(rows);log.info("MONKEY_LIVE_COMMIT events=%d state=%s",len(rows),STATE)
async def main():
 log.info("GOOL MONKEY LIVE TRUTH production Flashscore engine poll=%ss",POLL)
 while True:
  started=time.monotonic()
  try:await cycle()
  except Exception:log.exception("MONKEY_LIVE cycle failed")
  await asyncio.sleep(max(2.0,POLL-(time.monotonic()-started)))
if __name__=="__main__":asyncio.run(main())
