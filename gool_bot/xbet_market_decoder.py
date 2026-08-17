"""Shadow-only 1xBet market decoder focused on GOOL markets."""
from __future__ import annotations
import re
from collections import defaultdict
LABEL_KEYS={"N","Name","name","Title","title","GN","GroupName","groupName","Caption","caption","MarketName","marketName","PeriodName","periodName"}
TOTAL_TYPES={9:("over",4),10:("under",4),11:("over",5),12:("under",5),13:("over",6),14:("under",6)}
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
def _buckets(nodes):
    b=defaultdict(lambda:defaultdict(dict))
    for n in nodes:
        spec=TOTAL_TYPES.get(n.get("T"))
        if not spec:continue
        side,family=spec;p=_line(n)
        if p is None:continue
        key=(n.get("sg"),n.get("ge"),str(n.get("G","-")),family);b[key][p][side]=n
    return [{"sg":k[0],"ge":k[1],"g":k[2],"family":k[3],"pairs":dict(v)} for k,v in b.items()]
def _odd(node):return (node or {}).get("C","—")
def _fmt_pair(line,pair):return f"ТБ {line} <b>{_odd(pair.get('over'))}</b> · ТМ {line} <b>{_odd(pair.get('under'))}</b>"
def _is_half(p):return abs((float(p)%1)-0.5)<1e-9
def _pick_half(buckets,target):
    cand=[]
    for b in buckets:
        if target not in b["pairs"]:continue
        # Prefer explicit period total families (G/T 5 or 6) over generic family 4.
        score=(10 if b["family"] in (5,6) else 0)+(4 if all(_is_half(p) for p in b["pairs"]) else 0)+(2 if b["sg"] is not None else 0)-max(0,len(b["pairs"])-3)*.2
        cand.append((score,b))
    return max(cand,key=lambda x:x[0])[1] if cand else None
def _pick_full(buckets,exclude=None):
    cand=[]
    for b in buckets:
        if b is exclude or b["family"]!=4:continue
        pairs=b["pairs"];half=[p for p in pairs if _is_half(p)]
        if not half:continue
        score=8*(len(half)/max(1,len(pairs)))+min(len(half),6)+(4 if len(half)>=2 else 0)+(3 if len(pairs)==len(half) else 0)+(2 if b["sg"] is None else 0)
        cand.append((score,b))
    return max(cand,key=lambda x:x[0])[1] if cand else None
def _fingerprint(b):return f"SG={b.get('sg')} GE={b.get('ge')} G={b.get('g')} Tfam={b.get('family')}"
def _target_candidates(buckets,target):
    return [{"bucket":b,"pair":b["pairs"][target]} for b in buckets if target in b["pairs"]]
def _binary_type_pairs(nodes):
    groups=defaultdict(lambda:defaultdict(list))
    for n in nodes:groups[(n.get("sg"),n.get("ge"),str(n.get("G","-")))][str(n.get("T"))].append(n)
    out=[]
    for (sg,ge,g),types in groups.items():
        compact=[]
        for t,items in types.items():
            if len(items)==1:
                n=items[0]
                try:c=float(n.get("C"))
                except:continue
                if c>1:compact.append((t,n))
        if 2<=len(compact)<=8:out.append({"sg":sg,"ge":ge,"g":g,"items":sorted(compact,key=lambda z:z[0])})
    return out
def decode(game,current_goals,minute=0):
    nodes=collect_nodes(game);buckets=_buckets(nodes);target=float(current_goals)+.5;half=_pick_half(buckets,target) if int(minute or 0)<=45 else None;full=_pick_full(buckets,exclude=half)
    return {"count":len(nodes),"target":target,"minute":int(minute or 0),"half":half,"full":full,"buckets":buckets,"target_candidates":_target_candidates(buckets,target),"binary_type_pairs":_binary_type_pairs(nodes)}
def format_markets(d):
    target=d["target"];lines=[]
    if d.get("minute",0)<=45:
        lines.append("⏱ <b>ГОЛ В 1-М ТАЙМЕ</b>");h=d.get("half")
        lines.append((_fmt_pair(target,h["pairs"][target])+f" · <code>{_fingerprint(h)}</code>") if h else f"Тотал {target}: рынок не найден")
        cand=[]
        for x in d.get("target_candidates",[]):
            b=x["bucket"];p=x["pair"];cand.append(f"{_fingerprint(b)} O={_odd(p.get('over'))}/U={_odd(p.get('under'))}")
        if cand:lines.append("🔬 все кандидаты: <code>"+"; ".join(cand[:16])+"</code>")
    lines.append("🏁 <b>ТОТАЛЫ МАТЧА</b>");f=d.get("full")
    if f:
        for p in sorted(f["pairs"]):
            if _is_half(p):lines.append(_fmt_pair(p,f["pairs"][p]))
        lines.append(f"🔎 <code>{_fingerprint(f)}</code>")
    else:lines.append("рынок общего тотала пока не определён")
    lines.append("🤝 <b>ОБЕ ЗАБЬЮТ</b>");lines.append("рынок пока не расшифрован")
    cand=[]
    for b in d.get("binary_type_pairs",[]):
        vals=", ".join(f"T={t}:{_odd(n)}" for t,n in b["items"]);cand.append(f"SG={b['sg']} GE={b['ge']} G={b['g']} [{vals}]")
    if cand:lines.append("🔬 бинарные группы: <code>"+"; ".join(cand[:16])+"</code>")
    lines.append("⚠️ shadow: CORE не затронут")
    return lines
