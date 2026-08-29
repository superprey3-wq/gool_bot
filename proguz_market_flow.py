"""Historical market-flow analytics for Monkey PROGRUZ.

Pure Python + SQLite. Uses the odds snapshots Monkey already stores; no external API.
Measures de-vig fair-probability trajectory, velocity/acceleration, persistence,
source synchronisation, reversals and main-total line migration.
"""
from __future__ import annotations
import json,math,sqlite3,statistics,time
from collections import defaultdict
from pathlib import Path

try:
    from proguz_fair_probability import fair_consensus
except Exception:
    fair_consensus=None


def _side(row):
    s=str(row.get("side") or row.get("selection") or "").upper()
    return "OVER" if s in {"OVER","O","ТБ","TB"} else "UNDER" if s in {"UNDER","U","ТМ","TM"} else ""


def _scope(row):
    s=str(row.get("scope") or "FULL_TIME").upper().replace("-","_").replace(" ","_")
    return {"FULLTIME":"FULL_TIME","FT":"FULL_TIME","1H":"FIRST_HALF","2H":"SECOND_HALF"}.get(s,s)


def _source(row):
    b=str(row.get("bookmaker") or row.get("bookmaker_id") or "")
    src=str(row.get("source") or "").upper()
    if "1XBET" in b.upper() or "BETB2B" in src:return "1xBet"
    if "KAMBI" in b.upper() or "KAMBI" in src:return "Kambi/BetRivers"
    return b or src or "unknown"


def _f(v,default=None):
    try:return float(v)
    except (TypeError,ValueError):return default


def _median(xs,default=0.0):
    xs=[float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return statistics.median(xs) if xs else default


def _history(db_path,event_id,scope,lookback_seconds):
    db=Path(db_path)
    if not db.exists():return []
    c=None
    try:
        c=sqlite3.connect(db,timeout=5)
        cutoff=time.time()-float(lookback_seconds)
        rows=c.execute(
            "SELECT o.snapshot_id,s.ts,o.payload FROM odds o JOIN snapshots s ON s.id=o.snapshot_id "
            "WHERE s.complete=1 AND s.ts>=? AND o.event_id=? AND o.market IN ('TOTAL','OVER_UNDER') AND o.scope=? "
            "ORDER BY s.ts ASC,o.id ASC",
            (cutoff,str(event_id),str(scope)),
        ).fetchall()
        out=[]
        for sid,ts,payload in rows:
            try:r=json.loads(payload)
            except Exception:continue
            if isinstance(r,dict):out.append((int(sid),float(ts),r))
        return out
    except Exception:return []
    finally:
        if c:
            try:c.close()
            except Exception:pass


def _paired_points(rows,line,side):
    grouped=defaultdict(dict)
    for sid,ts,r in rows:
        if _scope(r)=="" or _f(r.get("line")) is None:continue
        if abs(float(r.get("line"))-float(line))>1e-6:continue
        sd=_side(r)
        if sd not in {"OVER","UNDER"}:continue
        odd=_f(r.get("odd"))
        if odd is None or odd<=1.01:continue
        grouped[(sid,_source(r))][sd]=(odd,ts)
    series=defaultdict(list)
    for (sid,src),pair in grouped.items():
        if "OVER" not in pair or "UNDER" not in pair:continue
        over,ots=pair["OVER"];under,uts=pair["UNDER"]
        fair=fair_consensus(over,under) if fair_consensus else {}
        if not fair:continue
        key="over" if side=="OVER" else "under"
        series[src].append({"ts":max(ots,uts),"p":float(fair[key]),"vig":float(fair.get("vig",0)),"method_spread_pp":float(fair.get("method_spread_pp",0))})
    for src in series:series[src].sort(key=lambda x:x["ts"])
    return series


def _series_metrics(points):
    if len(points)<2:return None
    a,b=points[0],points[-1];mins=max((b["ts"]-a["ts"])/60.0,1/60)
    move=(b["p"]-a["p"])*100.0;velocity=move/mins
    diffs=[(points[i]["p"]-points[i-1]["p"])*100.0 for i in range(1,len(points))]
    persistence=sum(1 for d in diffs if d>0.05)/len(diffs) if diffs else 0.0
    peak=points[0]["p"];max_drawdown=0.0
    for x in points[1:]:
        peak=max(peak,x["p"]);max_drawdown=max(max_drawdown,(peak-x["p"])*100.0)
    reversal=max_drawdown>=1.75 and move<max_drawdown
    accel=0.0
    if len(points)>=3:
        mid=len(points)//2;p0=points[0];pm=points[mid];p1=points[-1]
        m1=max((pm["ts"]-p0["ts"])/60.0,1/60);m2=max((p1["ts"]-pm["ts"])/60.0,1/60)
        v1=((pm["p"]-p0["p"])*100.0)/m1;v2=((p1["p"]-pm["p"])*100.0)/m2;accel=v2-v1
    threshold=a["p"]+0.015;first_hit=next((x["ts"] for x in points[1:] if x["p"]>=threshold),None)
    return {"move_pp":round(move,3),"velocity_pp_min":round(velocity,3),"acceleration_pp_min2":round(accel,3),"persistence":round(persistence,3),"reversal":bool(reversal),"first_hit_ts":first_hit,"samples":len(points),"fair_start":round(a["p"]*100,2),"fair_now":round(b["p"]*100,2),"method_spread_pp":round(_median([x.get("method_spread_pp") for x in points]),3)}


def _main_lines(rows):
    grouped=defaultdict(lambda:defaultdict(dict))
    tsmap={}
    for sid,ts,r in rows:
        line=_f(r.get("line"));sd=_side(r);odd=_f(r.get("odd"))
        if line is None or sd not in {"OVER","UNDER"} or odd is None or odd<=1.01:continue
        src=_source(r);grouped[(sid,src)][line][sd]=odd;tsmap[(sid,src)]=ts
    per_src=defaultdict(list)
    for key,lines in grouped.items():
        sid,src=key;choices=[]
        for line,pair in lines.items():
            if "OVER" not in pair or "UNDER" not in pair:continue
            fair=fair_consensus(pair["OVER"],pair["UNDER"]) if fair_consensus else {}
            if not fair:continue
            choices.append((abs(float(fair["over"])-0.5),line,float(fair["over"])))
        if choices:
            _,line,p=sorted(choices,key=lambda x:(x[0],x[1]))[0];per_src[src].append({"ts":tsmap[key],"line":line,"over_fair":p})
    for src in per_src:per_src[src].sort(key=lambda x:x["ts"])
    return per_src


def analyze(db_path,event_id,scope,line,side,lookback_seconds=900):
    side=str(side).upper();rows=_history(db_path,event_id,scope,lookback_seconds)
    if not rows:return {"available":False,"reason":"no_history"}
    series=_paired_points(rows,line,side);source_metrics={}
    for src,points in series.items():
        m=_series_metrics(points)
        if m:source_metrics[src]=m
    supportive={s:m for s,m in source_metrics.items() if m["move_pp"]>=0.75 and not m["reversal"]}
    hits=[m["first_hit_ts"] for m in supportive.values() if m.get("first_hit_ts")]
    sync_seconds=(max(hits)-min(hits)) if len(hits)>=2 else None
    main=_main_lines(rows);migrations={}
    oriented=[]
    for src,pts in main.items():
        if len(pts)<2:continue
        delta=float(pts[-1]["line"])-float(pts[0]["line"]);support=delta if side=="OVER" else -delta
        migrations[src]={"from":pts[0]["line"],"to":pts[-1]["line"],"delta":round(delta,3),"support":round(support,3)}
        if support>0:oriented.append(support)
    moves=[m["move_pp"] for m in supportive.values()];vel=[m["velocity_pp_min"] for m in supportive.values()];acc=[m["acceleration_pp_min2"] for m in supportive.values()];pers=[m["persistence"] for m in supportive.values()]
    fair_move=_median(moves);velocity=_median(vel);acceleration=_median(acc);persistence=_median(pers)
    migration=_median(oriented);migration_sources=len(oriented);reversal_sources=sum(1 for m in source_metrics.values() if m["reversal"])
    sync_confirmed=sync_seconds is not None and sync_seconds<=180
    flow_score=40.0+min(22.0,max(0.0,fair_move)*3.2)+min(10.0,max(0.0,velocity)*2.2)+min(7.0,max(0.0,acceleration)*1.5)+min(8.0,persistence*8.0)+min(8.0,migration*12.0)+(5.0 if sync_confirmed else 0.0)-min(15.0,reversal_sources*5.0)
    flow_score=max(0.0,min(100.0,flow_score))
    trajectory=[]
    all_ts=sorted({x["ts"] for pts in series.values() for x in pts})[-8:]
    for ts in all_ts:
        vals=[]
        for pts in series.values():
            near=[x for x in pts if abs(x["ts"]-ts)<=2]
            if near:vals.append(near[-1]["p"]*100)
        if vals:trajectory.append({"ts":round(ts,1),"fair_pct":round(_median(vals),2)})
    return {"available":bool(source_metrics),"lookback_s":int(lookback_seconds),"fair_sources":len(supportive),"paired_sources":len(source_metrics),"fair_move_pp":round(fair_move,3),"velocity_pp_min":round(velocity,3),"acceleration_pp_min2":round(acceleration,3),"persistence":round(persistence,3),"reversal_sources":reversal_sources,"sync_seconds":None if sync_seconds is None else round(sync_seconds,1),"sync_confirmed":sync_confirmed,"line_migration":round(migration,3),"line_migration_sources":migration_sources,"flow_score":round(flow_score,1),"source_metrics":source_metrics,"line_migrations":migrations,"trajectory":trajectory}
