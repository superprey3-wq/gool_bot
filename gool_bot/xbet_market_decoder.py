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
                for tag in ("SG","GE"):
                    m=re.search(rf"/{tag}\[(\d+)\]",path);row[tag.lower()]=int(m.group(1)) if m else None
                out.append(row)
        for k,v in obj.items():collect_nodes(v,out,f"{path}/{k}"[-180:],ctx)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):collect_nodes(v,out,f"{path}[{i}]"[-180:],context)
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
    return [{"sg":k[0],"ge":k[1],"g":k[2],"pairs":pair_totals(v)} for k,v in b.items()]
def _odd(node):return (node or {}).get("C","—")
def _fmt_pair(line,pair):return f"ТБ {line} <b>{_odd(pair.get('over'))}</b> · ТМ {line} <b>{_odd(pair.get('under'))}</b>"
def _is_half(p):return abs((float(p)%1)-0.5)<1e-9
def _pick_half(buckets,target):
    cand=[]
    for b in buckets:
        if target not in b["pairs"]:continue
        score=(5 if b["sg"]==0 else 0)+(4 if all(_is_half(p) for p in b["pairs"]) else 0)-max(0,len(b["pairs"])-3)*0.3
        cand.append((score,b))
    return max(cand,key=lambda x:x[0])[1] if cand else None
def _pick_full(buckets,exclude=None):
    cand=[]
    for b in buckets:
        if b is exclude:continue
        pairs=b["pairs"];half=[p for p in pairs if _is_half(p)]
        if not half:continue
        score=8*(len(half)/max(1,len(pairs)))+min(len(half),6)+(4 if len(half)>=2 else 0)+(3 if len(pairs)==len(half) else 0)
        cand.append((score,b))
    return max(cand,key=lambda x:x[0])[1] if cand else None
def _txt(n):return (" ".join(n.get("context") or [])+" "+str(n.get("N") or "")).lower()
def _yes_no_candidates(nodes):
    yes=no=None
    for n in nodes:
        txt=_txt(n)
        if "both teams" not in txt and "btts" not in txt and "обе заб" not in txt:continue
        if re.search(r"\b(yes|да)\b",txt):yes=n
        if re.search(r"\b(no|нет)\b",txt):no=n
    return yes,no
def _fingerprint(b):return f"SG={b.get('sg')} GE={b.get('ge')} G={b.get('g')}"
def _target_candidates(buckets,target):
    out=[]
    for b in buckets:
        pair=b["pairs"].get(target)
        if pair and (pair.get("over") or pair.get("under")):out.append({"bucket":b,"pair":pair})
    return out
def _binary_type_pairs(nodes):
    groups=defaultdict(lambda:defaultdict(list))
    for n in nodes:
        key=(n.get("sg"),n.get("ge"),str(n.get("G","-")))
        groups[key][str(n.get("T"))].append(n)
    out=[]
    for (sg,ge,g),types in groups.items():
        compact=[]
        for t,items in types.items():
            if len(items)==1:
                n=items[0]
                try:c=float(n.get("C"))
                except:continue
                if c>1:compact.append((t,n))
        if 2<=len(compact)<=8:
            compact=sorted(compact,key=lambda z:z[0])
            out.append({"sg":sg,"ge":ge,"g":g,"items":compact})
    return out
def decode(game,current_goals,minute=0):
    nodes=collect_nodes(game);buckets=_buckets(nodes);target=float(current_goals)+0.5
    half=_pick_half(buckets,target) if int(minute or 0)<=45 else None;full=_pick_full(buckets,exclude=half);y,n=_yes_no_candidates(nodes)
    return {"count":len(nodes),"target":target,"minute":int(minute or 0),"half":half,"full":full,"btts_yes":y,"btts_no":n,"buckets":buckets,"target_candidates":_target_candidates(buckets,target),"binary_type_pairs":_binary_type_pairs(nodes)}
def format_markets(d):
    target=d["target"];lines=[]
    if d.get("minute",0)<=45:
        lines.append("⏱ <b>ГОЛ В 1-М ТАЙМЕ</b>");h=d.get("half")
        lines.append((_fmt_pair(target,h["pairs"][target])+f" · <code>{_fingerprint(h)}</code>") if h else f"Тотал {target}: рынок не найден")
        cand=[]
        for x in d.get("target_candidates",[]):
            b=x["bucket"];p=x["pair"];cand.append(f"{_fingerprint(b)} O={_odd(p.get('over'))}/U={_odd(p.get('under'))}")
        if cand:lines.append("🔬 все кандидаты: <code>"+"; ".join(cand[:12])+"</code>")
    lines.append("🏁 <b>ТОТАЛЫ МАТЧА</b>");f=d.get("full")
    if f:
        for p in sorted(f["pairs"]):
            if _is_half(p):lines.append(_fmt_pair(p,f["pairs"][p]))
        lines.append(f"🔎 <code>{_fingerprint(f)}</code>")
    else:lines.append("рынок общего тотала пока не определён")
    lines.append("🤝 <b>ОБЕ ЗАБЬЮТ</b>");y,n=d.get("btts_yes"),d.get("btts_no")
    if y or n:lines.append(f"ДА <b>{_odd(y)}</b> · НЕТ <b>{_odd(n)}</b>")
    else:
        lines.append("рынок пока не расшифрован")
        cand=[]
        for b in d.get("binary_type_pairs",[]):
            vals=", ".join(f"T={t}:{_odd(n)}" for t,n in b["items"])
            cand.append(f"{_fingerprint(b)} [{vals}]")
        if cand:lines.append("🔬 бинарные группы: <code>"+"; ".join(cand[:12])+"</code>")
    lines.append("⚠️ shadow: CORE не затронут")
    return lines
