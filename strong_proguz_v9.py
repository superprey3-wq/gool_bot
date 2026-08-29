"""Runtime wrapper that upgrades strong_proguz_feed to PROGRUZ microstructure V9."""
from __future__ import annotations
import json,time
from http.server import ThreadingHTTPServer
import strong_proguz_feed as base
from proguz_market_flow import analyze as analyze_market_flow
from proguz_fair_probability import self_test as fair_self_test

FLOW_LOOKBACK=900
MIN_FAIR_MOVE_PP=1.0
_orig_candidate=base._candidate

def _flow_adjust(flow):
    if not flow.get("available"):return 0.0
    score=float(flow.get("flow_score") or 0)
    adj=max(-8.0,min(8.0,(score-60.0)*0.20))
    if flow.get("sync_confirmed"):adj+=2.0
    adj+=min(3.0,max(0.0,float(flow.get("line_migration") or 0))*5.0)
    adj-=min(4.0,float(flow.get("reversal_sources") or 0)*2.0)
    return round(max(-10.0,min(12.0,adj)),1)

def _candidate(key,rows,side,ctx):
    candidate=_orig_candidate(key,rows,side,ctx)
    if not candidate:return None
    eid,scope,line_txt=key
    try:line=float(line_txt);flow=analyze_market_flow(base.DB,eid,scope,line,side,FLOW_LOOKBACK) or {"available":False}
    except Exception as exc:
        print(f"PROGRUZ_FLOW_FAIL event={eid} pick={side}{line_txt} err={type(exc).__name__}",flush=True);flow={"available":False,"reason":type(exc).__name__}
    if flow.get("available"):
        paired=int(flow.get("paired_sources") or 0);fair_sources=int(flow.get("fair_sources") or 0);fair_move=float(flow.get("fair_move_pp") or 0);revs=int(flow.get("reversal_sources") or 0)
        if paired>=2 and fair_sources<2 and fair_move<MIN_FAIR_MOVE_PP:
            print(f"PROGRUZ_FLOW_REJECT event={eid} pick={side}{line:g} reason=devig_not_confirmed paired={paired} fair_sources={fair_sources} fair_move={fair_move:.2f}pp",flush=True);return None
        if paired>=2 and revs>paired/2:
            print(f"PROGRUZ_FLOW_REJECT event={eid} pick={side}{line:g} reason=trajectory_reversal paired={paired} reversals={revs}",flush=True);return None
    legacy=float(candidate.get("strength") or 0);adj=_flow_adjust(flow);score=round(max(0,min(100,legacy+adj)),1)
    if score<float(base.MIN_SCORE):return None
    candidate["legacy_strength"]=legacy;candidate["strength"]=score;candidate["market_flow_adjustment"]=adj;candidate["market_flow"]=flow
    print(f"PROGRUZ_V9_FLOW event={eid} pick={side}{line:g} fair_move={float(flow.get('fair_move_pp') or 0):+.2f}pp velocity={float(flow.get('velocity_pp_min') or 0):+.2f} accel={float(flow.get('acceleration_pp_min2') or 0):+.2f} persistence={float(flow.get('persistence') or 0):.2f} sync={int(bool(flow.get('sync_confirmed')))} line_migration={float(flow.get('line_migration') or 0):+.2f} flow_score={float(flow.get('flow_score') or 0):.0f} legacy={legacy:.0f} adj={adj:+.1f} final={score:.0f}",flush=True)
    return candidate

base._candidate=_candidate

def _do_get(self):
    p=self.path.split("?",1)[0]
    if p not in ("/","/strong","/bestbet","/health","/markets"):self.send_response(404);self.end_headers();return
    if p=="/bestbet":body=base.best_bet_payload()
    else:
        strong,source,meta,n,truth_events,err=base.strong_rows();body={"ok":True,"ts":time.time(),"mode":"LIVE_TOTAL_OU_MICROSTRUCTURE_V9","market_source":source,"market_records":n,"truth_events":truth_events,"truth_error":err,"min_move_pct":base.MIN_MOVE,"min_unpersisted_move_pct":base.MIN_UNPERSISTED_MOVE,"min_stats_keys":base.MIN_STATS_KEYS,"flow_lookback_seconds":FLOW_LOOKBACK,"min_fair_move_pp":MIN_FAIR_MOVE_PP,"market_flow_enabled":True,"live_stats_gate":True,"strong":strong}
    raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)

base.H.do_GET=_do_get

if __name__=="__main__":
    ok=False
    try:ok=bool(fair_self_test())
    except Exception as exc:print(f"PROGRUZ_DEVIG_SELFTEST_FAIL err={type(exc).__name__}",flush=True)
    print(f"GOOL_MARKET_SERVER MICROSTRUCTURE V9 port={base.PORT} devig_selftest={int(ok)} lookback={FLOW_LOOKBACK}s fair_gate={MIN_FAIR_MOVE_PP}pp",flush=True)
    ThreadingHTTPServer((base.HOST,base.PORT),base.H).serve_forever()
