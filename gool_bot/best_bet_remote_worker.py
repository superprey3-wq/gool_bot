"""Headless BEST BET worker for MonkeyBytes with unified Flashscore live truth."""
from __future__ import annotations
import asyncio,copy,json,logging,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s");log=logging.getLogger("best_bet_remote_worker")
STATE=Path(os.getenv("GOOL_REMOTE_BEST_BET_STATE","/home/container/remote_best_bet_state.json"));LIVE_TRUTH=Path(os.getenv("GOOL_MONKEY_LIVE_CONTEXT","/home/container/monkey_live_context.json"));POLL=max(30,int(os.getenv("GOOL_REMOTE_BEST_BET_POLL_SECONDS","60")));TRUTH_MAX_AGE=max(20,int(os.getenv("GOOL_MONKEY_LIVE_MAX_AGE","45")))
import visual_feed_unified_bot
import xg_proxy_patch,live_only_recommendation_patch,live_candidate_patch,candidate_enrichment_patch,scores365_enrichment_patch,deep_stats_consensus_patch,context_adjustment_patch,period_market_patch,phase_market_patch,multi_source_odds_patch,live_odds_freshness_patch,btts_period_sources_patch,team_total_sources_patch,sportsgameodds_patch,best_market_selector_patch,score_sync_patch,market_math_patch,gool_xg_consensus,odds_nonblocking_patch,best_bet_input_reliability_patch
import best_bet_engine as bbe
import best_bet_consensus_patch,best_bet_delivery_reliability_patch,best_bet_market_state_patch
_last_capture=None
def _capture_send(_png,caption):
 global _last_capture
 _last_capture={"caption":caption,"ts":int(time.time())};return True
bbe._send=_capture_send
def _write(payload):
 try:tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(STATE)
 except Exception as exc:log.warning("REMOTE_BEST_BET state write failed: %s",exc)
def _latest_best_bet():
 try:
  from signal_journal import all_signals
  rows=[r for r in all_signals() if r.get('kind')=='best_bet'];return max(rows,key=lambda r:int(r.get('created_ts',0) or r.get('last_seen_ts',0) or 0)) if rows else None
 except Exception:return None
def _truth():
 try:
  d=json.loads(LIVE_TRUTH.read_text(encoding='utf-8'));age=time.time()-float(d.get('ts') or 0);events=d.get('events') if isinstance(d.get('events'),dict) else {};return events,age
 except Exception:return {},9999.0
def _apply_truth(live):
 events,age=_truth()
 if age>TRUTH_MAX_AGE:
  log.warning("BEST_BET_TRUTH_STALE age=%.1fs; skip scan",age);return [],age,0
 out=[];synced=0
 for m in live:
  eid=str(getattr(m,'event_id','') or '');ctx=events.get(eid)
  if not isinstance(ctx,dict):continue
  try:p=copy.copy(m)
  except Exception:p=m
  for attr,key in (("home","home"),("away","away"),("home_score","home_score"),("away_score","away_score"),("minute","minute"),("status","status"),("league","league")):
   if key in ctx:
    try:setattr(p,attr,ctx[key])
    except Exception:pass
  stats=ctx.get('stats') if isinstance(ctx.get('stats'),dict) else {}
  try:setattr(p,'stats',copy.deepcopy(stats));setattr(p,'raw_stats',copy.deepcopy(stats))
  except Exception:pass
  try:
   ac=copy.deepcopy(getattr(p,'analysis_context',None) or {});ac['stats']=copy.deepcopy(stats);ac['live_stats']=copy.deepcopy(stats);ac['live_truth_source']='production_live_engine_flashscore';setattr(p,'analysis_context',ac)
  except Exception:pass
  out.append(p);synced+=1
  log.info("BEST_BET_TRUTH_OK event=%s score=%s:%s minute=%s stats=%d",eid,ctx.get('home_score'),ctx.get('away_score'),ctx.get('minute'),len(stats))
 return out,age,synced
async def cycle():
 global _last_capture
 _last_capture=None
 discovered=await visual_feed_unified_bot.unified_bot.discover_live_matches();live,truth_age,synced=_apply_truth(discovered)
 if not live:
  _write({"ts":int(time.time()),"live":0,"sent":0,"signal":None,"capture":None,"truth_age":round(truth_age,1),"truth_synced":synced});return
 score_sync_patch.reuse_once(live);sent=await asyncio.to_thread(bbe.scan,live);row=_latest_best_bet();payload={"ts":int(time.time()),"live":len(live),"sent":int(sent),"signal":row if sent and row else None,"capture":_last_capture,"truth_age":round(truth_age,1),"truth_synced":synced};_write(payload);log.info("REMOTE_BEST_BET_SCAN live=%d truth_synced=%d truth_age=%.1f sent=%d signal=%s",len(live),synced,truth_age,sent,(row or {}).get('primary'))
async def main():
 log.info("GOOL REMOTE BEST BET worker online unified_flash_truth=required poll=%ss",POLL)
 while True:
  started=time.monotonic()
  try:await cycle()
  except Exception:log.exception("REMOTE BEST BET cycle failed; continuing")
  await asyncio.sleep(max(2.0,POLL-(time.monotonic()-started)))
if __name__=='__main__':asyncio.run(main())
