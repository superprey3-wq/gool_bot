"""PROGRUZ V12: allow sustained cumulative steam to start a candidate.

V11 correctly handles a sharp one-snapshot leader + confirmation, but its rescue still
starts from per-snapshot delta_pct. A real steam can arrive as several smaller moves and
never produce a single 3% tick. V12 uses the existing 15-minute de-vig trajectory as a
second starter, while still requiring two paired sources, persistence/agreement, fresh
Flashscore truth and final strength >= the normal strong threshold.
"""
from __future__ import annotations
import json,os,time
from http.server import ThreadingHTTPServer
import strong_proguz_v9 as v11
base=v11.base
FLOW_LOOKBACK=v11.FLOW_LOOKBACK
MIN_CUM_FAIR_PP=float(os.getenv('GOOL_PROGRUZ_CUM_FAIR_MOVE_PP','1.5'))
MIN_CUM_FLOW=float(os.getenv('GOOL_PROGRUZ_CUM_FLOW_SCORE','64'))
MIN_CUM_PERSIST=float(os.getenv('GOOL_PROGRUZ_CUM_PERSISTENCE','0.45'))
_orig=base._candidate

def _current_price(rows,side):
 prices=[]
 for r in rows:
  if base._side(r)!=side:continue
  try:o=float(r.get('odd'))
  except Exception:continue
  if 1.30<=o<=3.20:prices.append(o)
 return max(prices) if prices else None

def _cumulative(key,rows,side,ctx):
 eid,scope,line_txt=key
 try:line=float(line_txt)
 except Exception:return None
 try:flow=v11.analyze_market_flow(base.DB,eid,scope,line,side,FLOW_LOOKBACK) or {'available':False}
 except Exception as exc:
  v11._audit('cum_flow_error',eid,side,line,extra={'error':type(exc).__name__});return None
 paired=int(flow.get('paired_sources') or 0);fair=int(flow.get('fair_sources') or 0);move=float(flow.get('fair_move_pp') or 0);fs=float(flow.get('flow_score') or 0);pers=float(flow.get('persistence') or 0);agree=float(flow.get('source_agreement') or 0);revs=int(flow.get('reversal_sources') or 0)
 if not flow.get('available') or paired<2 or fair<2 or move<MIN_CUM_FAIR_PP or fs<MIN_CUM_FLOW or pers<MIN_CUM_PERSIST or agree<.35 or revs>paired/2:
  v11._audit('reject_cumulative',eid,side,line,flow,{'paired':paired,'fair':fair,'required_move_pp':MIN_CUM_FAIR_PP,'required_flow':MIN_CUM_FLOW,'required_persistence':MIN_CUM_PERSIST});return None
 minute=int(ctx.get('minute') or 0);goals=int(ctx.get('home_score') or 0)+int(ctx.get('away_score') or 0)
 if minute<=0:return None
 if scope=='FULL_TIME' and side=='UNDER' and goals>=line:return None
 if scope=='FULL_TIME' and side=='OVER' and goals>line:return None
 if scope=='FIRST_HALF' and minute>45:return None
 if scope=='SECOND_HALF' and minute<46:return None
 live_adj,reject,diag=base._live_adjust(ctx,side)
 if reject=='insufficient_live_stats':return None
 if reject in {'under_conflicts_hot_live','over_dead_late_game'}:live_adj=-10
 elif reject=='under_late_pressure':live_adj=-8
 elif reject:live_adj=-7
 odd=_current_price(rows,side)
 if odd is None:return None
 score=58+min(16,move*5)+min(10,max(0,fs-55)*.5)+min(7,pers*7)+(4 if flow.get('sync_confirmed') else 0)+min(4,max(0,float(flow.get('line_migration') or 0))*6)+float(live_adj)-min(6,revs*2)
 score=round(max(0,min(100,score)),1)
 v11._audit('cumulative_candidate',eid,side,line,flow,{'score':score,'live_adjustment':live_adj,'passes':score>=float(base.MIN_SCORE)})
 if score<float(base.MIN_SCORE):return None
 sc=f"{int(ctx.get('home_score') or 0)}:{int(ctx.get('away_score') or 0)}"
 res={'id':'|'.join((eid,'TOTAL',scope,line_txt,side)),'event_id':eid,'home':ctx.get('home') or '','away':ctx.get('away') or '','score_live':sc,'minute':minute,'status':ctx.get('status') or 'LIVE','market':'TOTAL','scope':scope,'line':line,'side':side,'odd':odd,'books':fair,'moving_sources':sorted((flow.get('source_metrics') or {}).keys()),'median_delta_pct':round(-move,3),'persistent_books':fair,'strength':score,'legacy_strength':score,'live_stats':ctx.get('stats') or {},'live_stats_coverage':diag.get('coverage',0),'live_pressure':diag,'live_adjustment':live_adj,'live_truth_source':'production_live_engine_flashscore','candidate_path':'v12_cumulative','market_flow':flow,'market_flow_adjustment':0.0,'ts':time.time()}
 print(f"PROGRUZ_V12_CUMULATIVE event={eid} pick={side}{line:g} fair_move={move:+.2f}pp paired={paired} fair={fair} persistence={pers:.2f} agreement={agree:.2f} flow={fs:.0f} live_adj={live_adj:+.0f} strength={score:.0f}",flush=True)
 return res

def _candidate(key,rows,side,ctx):
 c=_orig(key,rows,side,ctx)
 return c if c else _cumulative(key,rows,side,ctx)
base._candidate=_candidate

def _get(self):
 p=self.path.split('?',1)[0]
 if p not in ('/','/strong','/bestbet','/health','/markets'):self.send_response(404);self.end_headers();return
 if p=='/bestbet':body=base.best_bet_payload()
 else:
  strong,source,meta,n,truth_events,err=base.strong_rows();body={'ok':True,'ts':time.time(),'mode':'LIVE_TOTAL_OU_MARKET_INTELLIGENCE_V12','market_source':source,'market_records':n,'truth_events':truth_events,'truth_error':err,'min_move_pct':base.MIN_MOVE,'second_confirm_move_pct':v11.SECOND_CONFIRM_MOVE,'cumulative_fair_move_pp':MIN_CUM_FAIR_PP,'cumulative_flow_score':MIN_CUM_FLOW,'cumulative_persistence':MIN_CUM_PERSIST,'flow_lookback_seconds':FLOW_LOOKBACK,'market_flow_enabled':True,'cumulative_steam_enabled':True,'live_stats_gate':'weighted','strong':strong}
 raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
base.H.do_GET=_get
if __name__=='__main__':
 ok=False
 try:ok=bool(v11.fair_self_test())
 except Exception as exc:print(f'PROGRUZ_DEVIG_SELFTEST_FAIL err={type(exc).__name__}',flush=True)
 print(f'GOOL_MARKET_SERVER MARKET_INTELLIGENCE V12 port={base.PORT} devig_selftest={int(ok)} cumulative=on cum_fair={MIN_CUM_FAIR_PP}pp cum_flow={MIN_CUM_FLOW} cum_persist={MIN_CUM_PERSIST}',flush=True)
 ThreadingHTTPServer((base.HOST,base.PORT),base.H).serve_forever()
