"""Shadow-only 1xBet market decoder focused on GOOL markets."""
from __future__ import annotations
import re
from collections import defaultdict
LABEL_KEYS={"N","Name","name","Title","title","GN","GroupName","groupName","Caption","caption","MarketName","marketName","PeriodName","periodName"}
def _label(v):
    if not isinstance(v,str):return ""
    s=" ".join(v.split()).strip();return s if s and len(s)<=100 and not re.fullmatch(r"[\d._:/-]+",s) else ""
def collect_nodes(obj,out=None,path="",context=()):
    if out is None:out=[]
    if isinstance(obj,dict):
        local=list(context)
        for k,v in obj.items():
            if k in LABEL_KEYS:
                x=_label(v)
                if x and x not in local:local.append(x)
        ctx=tuple(local[-8:])
        if "C" in obj and ("T" in obj or "P" in obj):
            try:odd=float(obj.get("C"))
            except:odd=0
            if odd>1:
                row={k:obj.get(k) for k in ("T","C","P","G","CE","CV","N","E") if k in obj};row["path"]=path;row["context"]=list(ctx)
                m=re.search(r"/SG\[(\d+)\]",path);row["sg"]=int(m.group(1)) if m else None
                m=re.search(r"/GE\[(\d+)\]",path);row["ge"]=int(m.group(1)) if m else None
                out.append(row)
        for k,v in obj.items():collect_nodes(v,out,f"{path}/{k}"[-160:],ctx)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):collect_nodes(v,out,f"{path}[{i}]"[-160:],context)
    return out
def _line(n):
    try:return float(n.get("P"))
    except:return None
def pair_totals(nodes):
    out=defaultdict(dict)
    for n in nodes:
        p=_line(n)
        if p is None:continue
        if n.get("T")==9:out[p]["over"]=n
        elif n.get("T")==10:out[p]["under"]=n
    return dict(out)
def _buckets(nodes):
    b=defaultdict(list)
    for n in nodes:
        if n.get("T") in (9,10):b[(n.get("sg"),n.get("ge"),str(n.get("G","-")))].append(n)
    out=[]
    for key,items in b.items():out.append({"sg":key[0],"ge":key[1],"g":key[2],"pairs":pair_totals(items)})
    return out
def _odd(node):return (node or {}).get("C","—")
def _fmt_pair(line,pair):return f"ТБ {line} <b>{_odd(pair.get('over'))}</b> · ТМ {line} <b>{_odd(pair.get('under'))}</b>"
def _candidate_score(bucket,target,period):
    pairs=bucket["pairs"]
    if target not in pairs:return -999
    score=0
    # Current compact feed consistently nests active period markets under SG.
    if bucket["sg"] is not None:score+=2
    # Prefer a bucket with several neighbouring total lines: this is a true totals ladder.
    score+=min(len(pairs),8)*0.25
    # First-half/current-period totals generally sit in an earlier SG; full-game ladder is retained separately.
    if period=="half":
        score+=3 if bucket["sg"]==0 else 0
    else:
        score+=2 if bucket["sg"] is None else 0
    return score
def _pick(buckets,target,period,exclude=None):
    ranked=sorted((( _candidate_score(b,target,period),b) for b in buckets if b is not exclude),key=lambda x:x[0],reverse=True)
    return ranked[0][1] if ranked and ranked[0][0]>-900 else None
def _yes_no_candidates(nodes):
    # Keep BTTS conservative: only expose when payload itself carries Yes/No text.
    yes=no=None
    for n in nodes:
        txt=(" ".join(n.get("context") or [])+" "+str(n.get("N") or "")).lower()
        if "both teams" not in txt and "btts" not in txt:continue
        if re.search(r"\byes\b",txt):yes=n
        if re.search(r"\bno\b",txt):no=n
    return yes,no
def decode(game,current_goals,minute=0):
    nodes=collect_nodes(game);buckets=_buckets(nodes);target=float(current_goals)+0.5
    half=None;full=None
    if int(minute or 0)<=45:half=_pick(buckets,target,"half")
    full=_pick(buckets,target,"full",exclude=half)
    y,n=_yes_no_candidates(nodes)
    return {"count":len(nodes),"target":target,"minute":int(minute or 0),"half":half,"full":full,"btts_yes":y,"btts_no":n,"buckets":buckets}
def format_markets(d):
    target=d["target"];lines=[]
    if d.get("minute",0)<=45:
        lines.append("⏱ <b>ГОЛ В 1-М ТАЙМЕ</b>")
        h=d.get("half")
        lines.append(_fmt_pair(target,h["pairs"][target]) if h else f"Тотал {target}: рынок не найден")
    lines.append("🏁 <b>ТОТАЛЫ МАТЧА</b>")
    f=d.get("full")
    if f:
        pairs=f["pairs"]
        for p in sorted(pairs):lines.append(_fmt_pair(p,pairs[p]))
    else:lines.append("рынок общего тотала пока не определён")
    lines.append("🤝 <b>ОБЕ ЗАБЬЮТ</b>")
    y,n=d.get("btts_yes"),d.get("btts_no")
    lines.append(f"ДА <b>{_odd(y)}</b> · НЕТ <b>{_odd(n)}</b>" if y or n else "рынок пока не расшифрован")
    lines.append("⚠️ shadow: CORE не затронут")
    return lines
