"""Shadow-only decoder for compact 1xBet LiveFeed market selections."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any
LABEL_KEYS={"N","Name","name","Title","title","GN","GroupName","groupName","Caption","caption","MarketName","marketName","PeriodName","periodName"}

def _label(v):
    if not isinstance(v,str):return ""
    s=" ".join(v.split()).strip()
    return s if s and len(s)<=100 and not re.fullmatch(r"[\d._:/-]+",s) else ""

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
                row={k:obj.get(k) for k in ("T","C","P","G","CE","CV","N","E") if k in obj};row["path"]=path;row["context"]=list(ctx);out.append(row)
        for k,v in obj.items():collect_nodes(v,out,f"{path}/{k}"[-140:],ctx)
    elif isinstance(obj,list):
        for i,v in enumerate(obj):collect_nodes(v,out,f"{path}[{i}]"[-140:],context)
    return out

def _ctx(n):return " | ".join(str(x) for x in n.get("context") or []).lower()
def classify(n):
    c=_ctx(n);total=any(x in c for x in ("total","over/under","over under"));first=any(x in c for x in ("1st half","first half","1-st half","half 1","1 half"));second=any(x in c for x in ("2nd half","second half","2-nd half","half 2","2 half"));team=any(x in c for x in ("team total","individual total","home total","away total"))
    if any(x in c for x in ("both teams to score","both teams score","btts")):return "btts"
    if any(x in c for x in ("next goal","team to score next","who will score next","next team to score")):return "next_goal"
    if total and first and not team:return "first_half_total"
    if total and second and not team:return "second_half_total"
    if total and not first and not second and not team:return "full_match_total"
    return "unknown"
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
def yes_no(nodes):
    yes=no=None
    for n in nodes:
        s=(" ".join(n.get("context") or [])+" "+str(n.get("N") or "")).lower()
        if re.search(r"\byes\b",s):yes=n
        elif re.search(r"\bno\b",s):no=n
    return {"yes":yes,"no":no}
def _group_diag(nodes):
    groups=defaultdict(list)
    for n in nodes:
        if n.get("T") in (9,10):groups[str(n.get("G","-"))].append(n)
    out=[]
    for g,items in groups.items():
        pairs=pair_totals(items);vals=[]
        for p,x in sorted(pairs.items()):
            vals.append(f"{p}:O={(x.get('over') or {}).get('C','—')}/U={(x.get('under') or {}).get('C','—')}")
        contexts=[]
        for n in items:
            c=" > ".join(n.get("context") or [])
            if c and c not in contexts:contexts.append(c)
        paths=[]
        for n in items:
            p=n.get("path") or ""
            if p and p not in paths:paths.append(p)
        out.append({"g":g,"count":len(items),"lines":vals[:12],"contexts":contexts[:2],"paths":paths[:2]})
    return sorted(out,key=lambda x:(-x["count"],x["g"]))
def decode(game,current_goals):
    nodes=collect_nodes(game);kinds=defaultdict(list)
    for n in nodes:kinds[classify(n)].append(n)
    first=pair_totals(kinds["first_half_total"]);full=pair_totals(kinds["full_match_total"]);target=current_goals+0.5
    return {"count":len(nodes),"target":target,"first":{"main":main_line(first),"lines":first},"full":{"main":main_line(full),"lines":full,"next":full.get(target,{})},"btts":yes_no(kinds["btts"]),"next_goal":yes_no(kinds["next_goal"]),"groups":_group_diag(nodes)}
def _fmt_total(x):return "не расшифрован по label" if not x else f"{x['line']} · ТБ <b>{x['over']}</b> · ТМ <b>{x['under']}</b>"
def format_markets(d):
    lines=["⏱ <b>1-Й ТАЙМ</b>",_fmt_total((d.get("first") or {}).get("main")),"🏁 <b>ВЕСЬ МАТЧ</b>",_fmt_total((d.get("full") or {}).get("main"))]
    ng=(d.get("full") or {}).get("next") or {}
    if ng:lines.append(f"🎯 Ещё 1 гол · ТБ {d.get('target')} <b>{(ng.get('over') or {}).get('C','—')}</b> · ТМ <b>{(ng.get('under') or {}).get('C','—')}</b>")
    b=d.get("btts") or {};lines.append(f"🤝 <b>ОБЕ ЗАБЬЮТ</b> · ДА <b>{(b.get('yes') or {}).get('C','—')}</b> · НЕТ <b>{(b.get('no') or {}).get('C','—')}</b>")
    n=d.get("next_goal") or {};lines.append(f"🥅 <b>СЛЕДУЮЩИЙ ГОЛ</b> · ДА/1 <b>{(n.get('yes') or {}).get('C','—')}</b> · НЕТ/2 <b>{(n.get('no') or {}).get('C','—')}</b>")
    lines.append("🔬 <b>T9/T10 ПО ГРУППАМ</b>")
    for g in (d.get("groups") or [])[:8]:
        lines.append(f"G={g['g']} ({g['count']}) · <code>{'; '.join(g['lines'][:6])}</code>")
        if g['contexts']:lines.append("ctx: <code>"+" || ".join(g['contexts'])[:350]+"</code>")
        if g['paths']:lines.append("path: <code>"+" || ".join(g['paths'])[:350]+"</code>")
    lines.append("⚠️ shadow: не влияет на CORE")
    return lines
