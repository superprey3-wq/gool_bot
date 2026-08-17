"""Shadow-only 1xBet decoder for confirmed GOOL football markets.

Confirmed:
- Full match totals: root G=4, T9/T10.
- BTTS: root G=22, T182/T183.
- First-half totals: use the subgame whose period metadata says first half
  (PN/NF), then its G=4 T9/T10 totals. Never infer 1H from price shape.
"""
from __future__ import annotations
import re
from collections import defaultdict

def _line(n):
    try:return float(n.get("P"))
    except:return None

def _text(v):return " ".join(str(v or "").lower().replace("ё","е").split())
def _is_first_half_label(v):
    s=_text(v)
    return any(x in s for x in ("1st half","first half","1-st half","1 half","1-й тайм","1 тайм","первый тайм"))

def _collect(obj,out=None,path="",period=None):
    if out is None:out=[]
    if isinstance(obj,dict):
        # SG items in GetGameZip can carry PN/P/N period metadata. Preserve it
        # for every nested selection so we identify the period structurally.
        local_period=period
        if re.search(r"/SG\[\d+\]$",path):
            labels=[]
            for k in ("PN","PeriodName","NF","N","Name"):
                if k in obj and isinstance(obj.get(k),str):labels.append(obj.get(k))
            p=obj.get("P")
            local_period={"labels":labels,"p":p,"first":any(_is_first_half_label(x) for x in labels)}
            # Historical/compact schema: P=1 is the first-half subgame. Only
            # accept this structural period id, never odds or SG array index.
            if not local_period["first"]:
                try:local_period["first"]=int(p)==1
                except:pass
        if "C" in obj and "T" in obj:
            try:odd=float(obj.get("C"))
            except:odd=0
            if odd>1:
                row={k:obj.get(k) for k in ("T","C","P","G","N","E") if k in obj}
                m=re.search(r"/SG\[(\d+)\]",path);row["sg"]=int(m.group(1)) if m else None
                m=re.search(r"/GE\[(\d+)\]",path);row["ge"]=int(m.group(1)) if m else None
                row["period"]=local_period
                out.append(row)
        for k,v in obj.items():_collect(v,out,f"{path}/{k}"[-200:],local_period)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):_collect(v,out,f"{path}[{i}]"[-200:],period)
    return out

def _pair(nodes,over_t=9,under_t=10):
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
    root=[n for n in nodes if n.get("sg") is None and str(n.get("G"))=="4" and n.get("T") in (9,10)]
    return _pair(root)

def _first_half_target(nodes,target):
    # Exact structural rule: first-half subgame + standard total market G=4.
    half=[n for n in nodes if n.get("sg") is not None and (n.get("period") or {}).get("first") and str(n.get("G"))=="4" and n.get("T") in (9,10)]
    pairs=_pair(half)
    return pairs.get(target)

def _btts(nodes):
    yes=no=None
    for n in nodes:
        if n.get("sg") is not None or str(n.get("G"))!="22":continue
        if n.get("T")==182:yes=n
        elif n.get("T")==183:no=n
    return yes,no

def decode(game,current_goals,minute=0):
    nodes=_collect(game);target=float(current_goals)+0.5
    full=_full_totals(nodes);half=_first_half_target(nodes,target) if int(minute or 0)<45 else None;yes,no=_btts(nodes)
    return {"count":len(nodes),"target":target,"minute":int(minute or 0),"half":half,"full":full,"btts_yes":yes,"btts_no":no}

def format_markets(d):
    lines=[];target=d["target"]
    if d.get("minute",0)<45:
        lines.append("⏱ <b>ГОЛ В 1-М ТАЙМЕ</b>");h=d.get("half");lines.append(_fmt(target,h) if h else f"ТБ {target}: коэффициент сейчас закрыт/не найден")
    lines.append("🏁 <b>ТОТАЛЫ МАТЧА</b>");full=d.get("full") or {};visible=[p for p in sorted(full) if _halfline(p)]
    if visible:
        for p in visible:lines.append(_fmt(p,full[p]))
    else:lines.append("тоталы сейчас закрыты/не найдены")
    lines.append("🤝 <b>ОБЕ ЗАБЬЮТ</b>");y,n=d.get("btts_yes"),d.get("btts_no");lines.append(f"ДА <b>{_odd(y)}</b> · НЕТ <b>{_odd(n)}</b>" if y or n else "рынок сейчас закрыт/не найден")
    lines.append("⚠️ shadow: CORE не затронут")
    return lines
