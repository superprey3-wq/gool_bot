"""Runtime wrapper: PROGRUZ V10 Market Intelligence on top of validated V8 gates."""
from __future__ import annotations
import json,os,time
from pathlib import Path
from http.server import ThreadingHTTPServer
import strong_proguz_feed as base
from proguz_market_flow import analyze as analyze_market_flow
from proguz_fair_probability import self_test as fair_self_test
FLOW_LOOKBACK=int(os.getenv('GOOL_PROGRUZ_FLOW_LOOKBACK_SECONDS','900'));MIN_FAIR_MOVE_PP=float(os.getenv('GOOL_PROGRUZ_MIN_FAIR_MOVE_PP','1.0'));AUDIT=Path(os.getenv('GOOL_PROGRUZ_AUDIT','/home/container/proguz_v10_audit.jsonl'));_orig=base._candidate

def _audit(kind,eid,side,line,flow=None,extra=None):
 try:
  row={'ts':time.time(),'kind':kind,'event_id':eid,'pick':f'{side}{line:g}'};row.update(extra or {})
  if flow:row['flow']={k:flow.get(k) for k in ('fair_sources','paired_sources','fair_move_pp','velocity_pp_min','acceleration_pp_min2','persistence','reversal_sources','sync_seconds','sync_confirmed','lead_source','lead_lag_seconds','source_agreement','source_spread_pp','line_migration','flow_score')}
  with AUDIT.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
 except Exception:pass

def _adjust(flow):
 if not flow.get('available'):return 0.0
 score=float(flow.get('flow_score') or 0);adj=max(-8,min(8,(score-60)*.20))
 if flow.get('sync_confirmed'):adj+=2
 adj+=min(3,max(0,float(flow.get('line_migration') or 0))*5)
 adj+=max(-2,min(2,(float(flow.get('source_agreement') or .5)-.5)*4))
 adj-=min(4,float(flow.get('reversal_sources') or 0)*2)
 return round(max(-10,min(12,adj)),1)

def _candidate(key,rows,side,ctx):
 c=_orig(key,rows,side,ctx)
 if not c:return None
 eid,scope,line_txt=key
 try:line=float(line_txt);flow=analyze_market_flow(base.DB,eid,scope,line,side,FLOW_LOOKBACK) or {'available':False}
 except Exception as exc:
  print(f'PROGRUZ_FLOW_FAIL event={eid} pick={side}{line_txt} err={type(exc).__name__}',flush=True);flow={'available':False,'reason':type(exc).__name__};line=float(line_txt)
 if flow.get('available'):
  paired=int(flow.get('paired_sources') or 0);fair=int(flow.get('fair_sources') or 0);move=float(flow.get('fair_move_pp') or 0);revs=int(flow.get('reversal_sources') or 0);agree=float(flow.get('source_agreement') or 0)
  if paired>=2 and fair<2 and move<MIN_FAIR_MOVE_PP:_audit('reject_devig',eid,side,line,flow);print(f'PROGRUZ_FLOW_REJECT event={eid} pick={side}{line:g} reason=devig_not_confirmed paired={paired} fair_sources={fair} fair_move={move:.2f}pp',flush=True);return None
  if paired>=2 and revs>paired/2:_audit('reject_reversal',eid,side,line,flow);print(f'PROGRUZ_FLOW_REJECT event={eid} pick={side}{line:g} reason=trajectory_reversal paired={paired} reversals={revs}',flush=True);return None
  if paired>=2 and agree<.30:_audit('reject_disagreement',eid,side,line,flow);print(f'PROGRUZ_FLOW_REJECT event={eid} pick={side}{line:g} reason=source_disagreement agreement={agree:.2f}',flush=True);return None
 legacy=float(c.get('strength') or 0);adj=_adjust(flow);score=round(max(0,min(100,legacy+adj)),1)
 _audit('candidate',eid,side,line,flow,{'legacy':legacy,'adjustment':adj,'final':score,'passes':score>=float(base.MIN_SCORE)})
 if score<float(base.MIN_SCORE):return None
 c['legacy_strength']=legacy;c['strength']=score;c['market_flow_adjustment']=adj;c['market_flow']=flow
 print(f"PROGRUZ_V10_FLOW event={eid} pick={side}{line:g} fair_move={float(flow.get('fair_move_pp') or 0):+.2f}pp velocity={float(flow.get('velocity_pp_min') or 0):+.2f} persistence={float(flow.get('persistence') or 0):.2f} sync={int(bool(flow.get('sync_confirmed')))} leader={flow.get('lead_source') or '-'} agreement={float(flow.get('source_agreement') or 0):.2f} line_migration={float(flow.get('line_migration') or 0):+.2f} flow={float(flow.get('flow_score') or 0):.0f} legacy={legacy:.0f} adj={adj:+.1f} final={score:.0f}",flush=True)
 return c
base._candidate=_candidate

def _get(self):
 p=self.path.split('?',1)[0]
 if p not in ('/','/strong','/bestbet','/health','/markets'):self.send_response(404);self.end_headers();return
 if p=='/bestbet':body=base.best_bet_payload()
 else:
  strong,source,meta,n,truth_events,err=base.strong_rows();body={'ok':True,'ts':time.time(),'mode':'LIVE_TOTAL_OU_MARKET_INTELLIGENCE_V10','market_source':source,'market_records':n,'truth_events':truth_events,'truth_error':err,'min_move_pct':base.MIN_MOVE,'min_unpersisted_move_pct':base.MIN_UNPERSISTED_MOVE,'min_stats_keys':base.MIN_STATS_KEYS,'flow_lookback_seconds':FLOW_LOOKBACK,'min_fair_move_pp':MIN_FAIR_MOVE_PP,'market_flow_enabled':True,'lead_lag_enabled':True,'source_agreement_enabled':True,'overnight_audit':str(AUDIT),'live_stats_gate':True,'strong':strong}
 raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
base.H.do_GET=_get
if __name__=='__main__':
 ok=False
 try:ok=bool(fair_self_test())
 except Exception as exc:print(f'PROGRUZ_DEVIG_SELFTEST_FAIL err={type(exc).__name__}',flush=True)
 print(f'GOOL_MARKET_SERVER MARKET_INTELLIGENCE V10 port={base.PORT} devig_selftest={int(ok)} lookback={FLOW_LOOKBACK}s fair_gate={MIN_FAIR_MOVE_PP}pp lead_lag=on agreement=on audit={AUDIT}',flush=True);ThreadingHTTPServer((base.HOST,base.PORT),base.H).serve_forever()
