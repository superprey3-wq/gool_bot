"""Shadow-only 1xBet decoder for confirmed GOOL football markets.

Confirmed from live 1xBet payload + on-screen checks:
- Full match totals: G=4, T=9 over / T=10 under, root game (SG=None).
- Both teams to score: G=22, T=182 yes / T=183 no, root game.
- First-half goal total: only use a subgame total (SG is not None) carrying the
  adaptive current-goals+0.5 line. Never guess from root/other markets.
"""
from __future__ import annotations
import re
from collections import defaultdict

TOTAL_TYPES={9:"over",10:"under",11:"over",12:"under",13:"over",14:"under"}

def _line(n):
    try:return float(n.get("P"))
    except:return None

def _collect(obj,out=None,path=""):
    if out is None:out=[]
    if isinstance(obj,dict):
        if "C" in obj and "T" in obj:
            try:odd=float(obj.get("C"))
            except:odd=0
            if odd>1:
                row={k:obj.get(k) for k in ("T","C","P","G","N","E") if k in obj}
                m=re.search(r"/SG\[(\d+)\]",path);row["sg"]=int(m.group(1)) if m else None
                m=re.search(r"/GE\[(\d+)\]",path);row["ge"]=int(m.group(1)) if m else None
                out.append(row)
        for k,v in obj.items():_collect(v,out,f"{path}/{k}"[-180:])
    elif isinstance(obj,list):
        for i,v in enumerate(obj):_collect(v,out,f"{path}[{i}]"[-180:])
    return out

def _pair(nodes,over_t,under_t):
    by=defaultdict(dict)
    for n in nodes:
        p=_line(n)
        if p is None:continue
        if n.get("T")==over_t:by[p]["over"]=n
        elif n.get("T")==under_t:by[p]["under"]=n
    return dict(by)

def _odd(n):return (n or {}).get("C","—")
def _fmt(line,p):return f"ТБ {line} <b>{_odd(p.get('over'))}</b> · ТМ {line} <b>{_odd(p.get('under'))}</b>"
def _halfline(x):return abs((float(x)%1)-0.5)<1e-9

def _full_totals(nodes):
    # Hard rule: root game, G=4, T9/T10 only.
    root=[n for n in nodes if n.get("sg") is None and str(n.get("G"))=="4" and n.get("T") in (9,10)]
    return _pair(root,9,10)

def _first_half_target(nodes,target):
    # Only subgame totals. This intentionally returns None rather than a wrong
    # coefficient when the feed does not expose a clear 1H market.
    candidates=[]
    for over_t,under_t in ((9,10),(11,12),(13,14)):
        sub=[n for n in nodes if n.get("sg") is not None and n.get("T") in (over_t,under_t)]
        pairs=_pair(sub,over_t,under_t)
        if target not in pairs:continue
        p=pairs[target]
        try:o=float((p.get("over") or {}).get("C"));u=float((p.get("under") or {}).get("C"))
        except:continue
        # Prefer a genuine two-sided market and prices closest to balanced.
        candidates.append((abs(o-u),p))
    return min(candidates,key=lambda x:x[0])[1] if candidates else None

def _btts(nodes):
    yes=no=None
    for n in nodes:
        if n.get("sg") is not None or str(n.get("G"))!="22":continue
        if n.get("T")==182:yes=n
        elif n.get("T")==183:no=n
    return yes,no

def decode(game,current_goals,minute=0):
    nodes=_collect(game);target=float(current_goals)+0.5
    full=_full_totals(nodes)
    half=_first_half_target(nodes,target) if int(minute or 0)<45 else None
    yes,no=_btts(nodes)
    return {"count":len(nodes),"target":target,"minute":int(minute or 0),"half":half,"full":full,"btts_yes":yes,"btts_no":no}

def format_markets(d):
    lines=[];target=d["target"]
    if d.get("minute",0)<45:
        lines.append("⏱ <b>ГОЛ В 1-М ТАЙМЕ</b>")
        h=d.get("half");lines.append(_fmt(target,h) if h else f"ТБ {target}: коэффициент не найден")
    lines.append("🏁 <b>ТОТАЛЫ МАТЧА</b>")
    full=d.get("full") or {}
    visible=[p for p in sorted(full) if _halfline(p)]
    if visible:
        for p in visible:lines.append(_fmt(p,full[p]))
    else:lines.append("тоталы сейчас закрыты/не найдены")
    lines.append("🤝 <b>ОБЕ ЗАБЬЮТ</b>")
    y,n=d.get("btts_yes"),d.get("btts_no")
    lines.append(f"ДА <b>{_odd(y)}</b> · НЕТ <b>{_odd(n)}</b>" if y or n else "рынок сейчас закрыт/не найден")
    lines.append("⚠️ shadow: CORE не затронут")
    return lines
