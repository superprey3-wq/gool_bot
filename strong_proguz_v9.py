"""Runtime wrapper: PROGRUZ V11 balanced market intelligence.

V11 keeps the validated V8 path, but fixes two production problems observed overnight:
(1) V8 required the median move of all confirmations to exceed the primary threshold,
which discarded a strong leader followed by a smaller confirming bookmaker move;
(2) live/flow context could veto a real market steam before strength scoring.
V11 accepts a strong primary move plus an independent directional confirmation, then
uses live context and de-vig microstructure as bounded score adjustments. Every rescue
rejection is written to the overnight audit so a zero-signal night is diagnosable.
"""
from __future__ import annotations
import json,os,statistics,time
from collections import defaultdict
from pathlib import Path
from http.server import ThreadingHTTPServer
import strong_proguz_feed as base
from proguz_market_flow import analyze as analyze_market_flow
from proguz_fair_probability import self_test as fair_self_test
FLOW_LOOKBACK=int(os.getenv('GOOL_PROGRUZ_FLOW_LOOKBACK_SECONDS','900'))
MIN_FAIR_MOVE_PP=float(os.getenv('GOOL_PROGRUZ_MIN_FAIR_MOVE_PP','1.0'))
SECOND_CONFIRM_MOVE=float(os.getenv('GOOL_PROGRUZ_SECOND_CONFIRM_MOVE','0.8'))
AUDIT=Path(os.getenv('GOOL_PROGRUZ_AUDIT','/home/container/proguz_v11_audit.jsonl'))
_orig=base._candidate

def _audit(kind,eid,side,line,flow=None,extra=None):
 try:
  row={'ts':time.time(),'kind':kind,'event_id':eid,'pick':f'{side}{line:g}'};row.update(extra or {})
  if flow:row['flow']={k:flow.get(k) for k in ('fair_sources','paired_sources','fair_move_pp','velocity_pp_min','acceleration_pp_min2','persistence','reversal_sources','sync_seconds','sync_confirmed','lead_source','lead_lag_seconds','source_agreement','source_spread_pp','line_migration','flow_score')}
  with AUDIT.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 except Exception:pass

def _flow_adjust(flow):
 if not flow.get('available'):return 0.0
 score=float(flow.get('flow_score') or 0);adj=max(-7,min(8,(score-58)*.18))
 paired=int(flow.get('paired_sources') or 0);fair=int(flow.get('fair_sources') or 0);move=float(flow.get('fair_move_pp') or 0);revs=int(flow.get('reversal_sources') or 0);agree=float(flow.get('source_agreement') or .5)
 if flow.get('sync_confirmed'):adj+=2
 adj+=min(3,max(0,float(flow.get('line_migration') or 0))*5)
 if paired>=2 and fair<2 and move<MIN_FAIR_MOVE_PP:adj-=5
 if paired>=2 and agree<.30:adj-=4
 adj-=min(6,revs*2.5)
 return round(max(-12,min(12,adj)),1)

def _rescue_candidate(key,rows,side,ctx):
 eid,scope,line_txt=key
 try:line=float(line_txt)
 except Exception:return None
 books=defaultdict(list)
 for r in rows:books[(base._src(r),str(r.get('bookmaker_id') or ''))].append(r)
 supporters=[];own=[];persist=0
 for bid,br in books.items():
  v,p,rev,o=base._pair_support(br,side)
  if v is None or v<0.6 or rev or o is None:continue
  supporters.append((bid,float(v),o));own.append(o);persist+=int(bool(p))
 sources={x[0][0] for x in supporters};conf=len(sources)
 moves=sorted((x[1] for x in supporters),reverse=True)
 primary=moves[0] if moves else 0.0;secondary=moves[1] if len(moves)>1 else 0.0
 if conf<2:
  _audit('reject_confirmations',eid,side,line,extra={'confirmations':conf,'primary_move':round(primary,3)});return None
 if primary<float(base.MIN_MOVE) or secondary<SECOND_CONFIRM_MOVE:
  _audit('reject_move_shape',eid,side,line,extra={'confirmations':conf,'primary_move':round(primary,3),'secondary_move':round(secondary,3),'primary_required':float(base.MIN_MOVE),'secondary_required':SECOND_CONFIRM_MOVE});return None
 if persist<=0 and primary<float(base.MIN_UNPERSISTED_MOVE):
  _audit('reject_unpersisted',eid,side,line,extra={'primary_move':round(primary,3),'required':float(base.MIN_UNPERSISTED_MOVE)});return None
 minute=int(ctx.get('minute') or 0);goals=int(ctx.get('home_score') or 0)+int(ctx.get('away_score') or 0)
 if minute<=0:return None
 if scope=='FULL_TIME' and side=='UNDER' and goals>=line:return None
 if scope=='FULL_TIME' and side=='OVER' and goals>line:return None
 if scope=='FIRST_HALF' and minute>45:return None
 if scope=='SECOND_HALF' and minute<46:return None
 live_adj,reject,diag=base._live_adjust(ctx,side)
 if reject=='insufficient_live_stats':
  _audit('reject_live_stats',eid,side,line,extra={'coverage':diag.get('coverage',0)});return None
 # A strong market move is no longer killed only because current match pressure disagrees.
 # Pressure remains important through a sizeable negative adjustment.
 if reject=='under_conflicts_hot_live':live_adj=-10
 elif reject=='under_late_pressure':live_adj=-8
 elif reject=='over_dead_late_game':live_adj=-10
 elif reject:live_adj=-7
 score=58+min(14,conf*4)+min(15,primary*2.8)+min(8,secondary*2)+min(6,persist*2)+float(live_adj)
 score=round(max(0,min(100,score)),1)
 if score<float(base.MIN_SCORE):
  _audit('reject_rescue_score',eid,side,line,extra={'score':score,'primary_move':round(primary,3),'secondary_move':round(secondary,3),'confirmations':conf,'persistent':persist,'live_adjustment':live_adj});return None
 prices=[]
 for r in own:
  try:o=float(r.get('odd'))
  except Exception:continue
  if 1.30<=o<=3.20:prices.append(o)
 if not prices:
  _audit('reject_price',eid,side,line,extra={'score':score});return None
 odd=max(prices);sc=f"{int(ctx.get('home_score') or 0)}:{int(ctx.get('away_score') or 0)}"
 res={'id':'|'.join((eid,'TOTAL',scope,line_txt,side)),'event_id':eid,'home':ctx.get('home') or '','away':ctx.get('away') or '','score_live':sc,'minute':minute,'status':ctx.get('status') or 'LIVE','market':'TOTAL','scope':scope,'line':line,'side':side,'odd':odd,'books':conf,'moving_sources':sorted(sources),'median_delta_pct':round(-statistics.median(moves),3),'primary_move_pct':round(primary,3),'secondary_move_pct':round(secondary,3),'persistent_books':persist,'strength':score,'live_stats':ctx.get('stats') or {},'live_stats_coverage':diag.get('coverage',0),'live_pressure':diag,'live_adjustment':live_adj,'live_truth_source':'production_live_engine_flashscore','candidate_path':'v11_rescue','ts':time.time()}
 _audit('rescue_candidate',eid,side,line,extra={'score':score,'primary_move':round(primary,3),'secondary_move':round(secondary,3),'confirmations':conf,'persistent':persist,'live_adjustment':live_adj})
 print(f"PROGRUZ_V11_RESCUE event={eid} pick={side}{line:g} primary={primary:.2f}% secondary={secondary:.2f}% confirms={conf} persistent={persist} live_adj={live_adj:+.0f} strength={score:.0f}",flush=True)
 return res

def _candidate(key,rows,side,ctx):
 c=_orig(key,rows,side,ctx);path='v8'
 if not c:
  c=_rescue_candidate(key,rows,side,ctx);path='v11_rescue'
 if not c:return None
 eid,scope,line_txt=key;line=float(line_txt)
 try:flow=analyze_market_flow(base.DB,eid,scope,line,side,FLOW_LOOKBACK) or {'available':False}
 except Exception as exc:
  print(f'PROGRUZ_FLOW_FAIL event={eid} pick={side}{line_txt} err={type(exc).__name__}',flush=True);flow={'available':False,'reason':type(exc).__name__}
 legacy=float(c.get('strength') or 0);adj=_flow_adjust(flow);score=round(max(0,min(100,legacy+adj)),1)
 _audit('candidate_final',eid,side,line,flow,{'path':path,'legacy':legacy,'adjustment':adj,'final':score,'passes':score>=float(base.MIN_SCORE)})
 if score<float(base.MIN_SCORE):return None
 c['legacy_strength']=legacy;c['strength']=score;c['market_flow_adjustment']=adj;c['market_flow']=flow;c['candidate_path']=c.get('candidate_path') or path
 print(f"PROGRUZ_V11_FLOW event={eid} pick={side}{line:g} path={path} fair_move={float(flow.get('fair_move_pp') or 0):+.2f}pp velocity={float(flow.get('velocity_pp_min') or 0):+.2f} persistence={float(flow.get('persistence') or 0):.2f} sync={int(bool(flow.get('sync_confirmed')))} leader={flow.get('lead_source') or '-'} agreement={float(flow.get('source_agreement') or 0):.2f} line_migration={float(flow.get('line_migration') or 0):+.2f} flow={float(flow.get('flow_score') or 0):.0f} legacy={legacy:.0f} adj={adj:+.1f} final={score:.0f}",flush=True)
 return c
base._candidate=_candidate

def _get(self):
 p=self.path.split('?',1)[0]
 if p not in ('/','/strong','/bestbet','/health','/markets'):self.send_response(404);self.end_headers();return
 if p=='/bestbet':body=base.best_bet_payload()
 else:
  strong,source,meta,n,truth_events,err=base.strong_rows();body={'ok':True,'ts':time.time(),'mode':'LIVE_TOTAL_OU_MARKET_INTELLIGENCE_V11','market_source':source,'market_records':n,'truth_events':truth_events,'truth_error':err,'min_move_pct':base.MIN_MOVE,'second_confirm_move_pct':SECOND_CONFIRM_MOVE,'min_unpersisted_move_pct':base.MIN_UNPERSISTED_MOVE,'min_stats_keys':base.MIN_STATS_KEYS,'flow_lookback_seconds':FLOW_LOOKBACK,'min_fair_move_pp':MIN_FAIR_MOVE_PP,'market_flow_enabled':True,'lead_lag_enabled':True,'source_agreement_enabled':True,'rescue_path_enabled':True,'overnight_audit':str(AUDIT),'live_stats_gate':'weighted','strong':strong}
 raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
base.H.do_GET=_get
if __name__=='__main__':
 ok=False
 try:ok=bool(fair_self_test())
 except Exception as exc:print(f'PROGRUZ_DEVIG_SELFTEST_FAIL err={type(exc).__name__}',flush=True)
 print(f'GOOL_MARKET_SERVER MARKET_INTELLIGENCE V11 port={base.PORT} devig_selftest={int(ok)} lookback={FLOW_LOOKBACK}s primary_move={base.MIN_MOVE}% secondary_confirm={SECOND_CONFIRM_MOVE}% live_gate=weighted audit={AUDIT}',flush=True);ThreadingHTTPServer((base.HOST,base.PORT),base.H).serve_forever()
