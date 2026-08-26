"""Enhanced secondary market node: expose several strongest current markets per LIVE match."""
from __future__ import annotations
import time
import market_node as mn

_ORIG_COMPACT = mn._compact_events


def _signal(mk, sel, now):
    pts=[]
    for raw in sel.get("points") or []:
        try:
            ts=float(raw[0]); odd=float(raw[1]); line=None if raw[2] is None else float(raw[2])
        except Exception:
            continue
        if odd>1 and ts>=now-600:
            pts.append([ts,odd,line])
    if len(pts)<2:
        return None
    first,last=pts[0],pts[-1]
    elapsed=max(1.0,last[0]-first[0])
    delta=(1/last[1]-1/first[1])*100
    line_move=0.0
    if first[2] is not None and last[2] is not None:
        line_move=last[2]-first[2]
    susp=int(sel.get("suspends",0) or 0); reop=int(sel.get("reopens",0) or 0)
    reopen_delta=float(sel.get("last_reopen_delta_pp",0) or 0)
    purple=abs(delta)>=4 or (susp>=2 and abs(reopen_delta)>=1.5) or (susp>=1 and reop>=1 and abs(reopen_delta)>=3)
    dot="🟣" if purple else "🟡" if abs(delta)<1.5 else "🟢" if delta>0 else "🔴"
    strength=abs(delta)+min(2.,abs(line_move)*2.)+min(2.,susp*.5+reop*.5)+min(2.,abs(reopen_delta)*.35)+(3. if purple else 0.)
    return {
        "market_key":mk,"market":mn._label(sel),"dot":dot,"delta_pp":round(delta,2),
        "elapsed":int(elapsed),"line_move":round(line_move,2),"suspends":susp,"reopens":reop,
        "reopen_delta_pp":round(reopen_delta,2),"start_odds":round(first[1],3),"last_odds":round(last[1],3),
        "start_line":first[2],"last_line":last[2],"updated":last[0],"strength":round(strength,2),
        "group_id":sel.get("group_id"),"type_id":sel.get("type_id"),"period":sel.get("period"),"name":sel.get("name"),
    }


def _top_markets(row, now, limit=5):
    signals=[]
    for mk,sel in (row.get("markets") or {}).items():
        sig=_signal(mk,sel,now)
        if sig: signals.append(sig)
    signals.sort(key=lambda s:(s["strength"],abs(s["delta_pp"]),s["updated"]),reverse=True)
    out=[]; seen=set()
    for s in signals:
        key=(s.get("type_id"),s.get("last_line"),s.get("period"))
        if key in seen: continue
        seen.add(key); out.append(s)
        if len(out)>=limit: break
    return out


def _fixture_meta(src):
    fs_id=str(src.get("fs_id") or "")
    fixture={}
    if fs_id:
        fixture=mn.FS_MATCHES.get(fs_id) or mn.FIXTURES.get(fs_id) or {}
    league=str(fixture.get("league") or src.get("league") or "").strip()
    country=str(fixture.get("country") or src.get("country") or "").strip()
    return league,country


def _compact_events_multi():
    out=_ORIG_COMPACT(); now=time.time()
    for k,row in out.items():
        src=mn.STATE.get(k) or {}
        top=_top_markets(src,now,5)
        league,country=_fixture_meta(src)
        row["league"]=league
        row["country"]=country
        row["tournament"]=league
        row["top_markets"]=top
        if top:
            row["best_market_start_odds"]=top[0].get("start_odds")
            row["best_market_last_odds"]=top[0].get("last_odds")
    return out

mn._compact_events=_compact_events_multi

if __name__=="__main__":
    mn.main()
