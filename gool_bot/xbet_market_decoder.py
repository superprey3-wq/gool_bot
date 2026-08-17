"""Shadow-only decoder for compact 1xBet LiveFeed market selections."""
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
def main_line(pairs):
    best=None
    for p,d in pairs.items():
        try:o=float((d.get("over") or {}).get("C"));u=float((d.get("under") or {}).get("C"))
        except:continue
        v=abs(o-u)
        if best is None or v<best[0]:best=(v,p,o,u)
    return None if best is None else {"line":best[1],"over":best[2],"under":best[3]}
def _buckets(nodes):
    b=defaultdict(list)
    for n in nodes:
        if n.get("T") in (9,10):b[(n.get("sg"),n.get("ge"),str(n.get("G","-")))].append(n)
    out=[]
    for (sg,ge,g),items in b.items():
        pairs=pair_totals(items);vals=[]
        for p,x in sorted(pairs.items()):vals.append(f"{p}:O={(x.get('over') or {}).get('C','—')}/U={(x.get('under') or {}).get('C','—')}")
        out.append({"sg":sg,"ge":ge,"g":g,"count":len(items),"pairs":pairs,"main":main_line(pairs),"lines":vals})
    return sorted(out,key=lambda x:((99 if x['sg'] is None else x['sg']),(99 if x['ge'] is None else x['ge']),x['g']))
def _types(nodes):
    d=defaultdict(list)
    for n in nodes:d[str(n.get("T"))].append(n)
    out=[]
    for t,items in d.items():
        sample=[]
        for n in items[:4]:sample.append(f"P={n.get('P','-')} C={n.get('C')} G={n.get('G','-')} SG={n.get('sg')} GE={n.get('ge')}")
        out.append((len(items),t,sample))
    return sorted(out,reverse=True)
def decode(game,current_goals):
    nodes=collect_nodes(game);return {"count":len(nodes),"target":current_goals+0.5,"buckets":_buckets(nodes),"types":_types(nodes)}
def format_markets(d):
    lines=["🔬 <b>1xBET STRUCTURE MAP</b>","T9/T10 разбиты по SG → GE → G:"]
    for b in (d.get("buckets") or [])[:14]:
        main=b.get("main");ms=""
        if main:ms=f" · баланс≈{main['line']} ({main['over']}/{main['under']})"
        lines.append(f"• SG={b['sg']} GE={b['ge']} G={b['g']} ({b['count']}){ms}")
        lines.append("  <code>"+"; ".join(b['lines'][:8])+"</code>")
    lines.append("🧩 <b>ДРУГИЕ T-КОДЫ</b>")
    for count,t,sample in (d.get("types") or [])[:14]:
        if t in ("9","10"):continue
        lines.append(f"• T={t} ×{count}: <code>{'; '.join(sample)[:300]}</code>")
    lines.append("⚠️ shadow: пока только карта структуры, CORE не затронут")
    return lines
