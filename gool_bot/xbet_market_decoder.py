"""Shadow-only decoder for compact 1xBet LiveFeed market selections."""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any

LABEL_KEYS={"N","Name","name","Title","title","GN","GroupName","groupName","Caption","caption","MarketName","marketName","PeriodName","periodName"}


def _label(v: Any) -> str:
    if not isinstance(v,str): return ""
    s=" ".join(v.split()).strip()
    if not s or len(s)>100 or re.fullmatch(r"[\d._:/-]+",s): return ""
    return s


def collect_nodes(obj: Any, out: list[dict[str,Any]]|None=None, path: str="", context: tuple[str,...]=()) -> list[dict[str,Any]]:
    if out is None: out=[]
    if isinstance(obj,dict):
        local=list(context)
        for k,v in obj.items():
            if k in LABEL_KEYS:
                x=_label(v)
                if x and x not in local: local.append(x)
        ctx=tuple(local[-8:])
        if "C" in obj and ("T" in obj or "P" in obj):
            try: odd=float(obj.get("C"))
            except (TypeError,ValueError): odd=0
            if odd>1:
                row={k:obj.get(k) for k in ("T","C","P","G","CE","CV","N","E") if k in obj}
                row["path"]=path;row["context"]=list(ctx);out.append(row)
        for k,v in obj.items(): collect_nodes(v,out,f"{path}/{k}"[-140:],ctx)
    elif isinstance(obj,list):
        for i,v in enumerate(obj): collect_nodes(v,out,f"{path}[{i}]"[-140:],context)
    return out


def _ctx(n: dict[str,Any]) -> str:
    return " | ".join(str(x) for x in n.get("context") or []).lower()


def classify(n: dict[str,Any]) -> str:
    c=_ctx(n)
    total=any(x in c for x in ("total","over/under","over under"))
    first=any(x in c for x in ("1st half","first half","1-st half","half 1","1 half"))
    second=any(x in c for x in ("2nd half","second half","2-nd half","half 2","2 half"))
    team=any(x in c for x in ("team total","individual total","home total","away total"))
    if any(x in c for x in ("both teams to score","both teams score","btts")): return "btts"
    if any(x in c for x in ("next goal","team to score next","who will score next","next team to score")): return "next_goal"
    if total and first and not team: return "first_half_total"
    if total and second and not team: return "second_half_total"
    if total and not first and not second and not team: return "full_match_total"
    return "unknown"


def _line(n):
    try:return float(n.get("P"))
    except (TypeError,ValueError):return None


def pair_totals(nodes: list[dict[str,Any]]) -> dict[float,dict[str,dict[str,Any]]]:
    """Pair compact T9/T10 only inside a market whose scope was classified."""
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
        except (TypeError,ValueError):continue
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


def decode(game: dict[str,Any], current_goals: int) -> dict[str,Any]:
    nodes=collect_nodes(game)
    kinds=defaultdict(list)
    for n in nodes:kinds[classify(n)].append(n)
    first=pair_totals(kinds["first_half_total"]);full=pair_totals(kinds["full_match_total"])
    target=current_goals+0.5
    unknown=pair_totals([n for n in kinds["unknown"] if n.get("T") in (9,10)])
    return {
        "count":len(nodes),"target":target,
        "first":{"main":main_line(first),"lines":first},
        "full":{"main":main_line(full),"lines":full,"next":full.get(target,{})},
        "btts":yes_no(kinds["btts"]),"next_goal":yes_no(kinds["next_goal"]),
        "unknown_t910":unknown,
    }


def _fmt_total(x):
    if not x:return "не расшифрован по label"
    return f"{x['line']} · ТБ <b>{x['over']}</b> · ТМ <b>{x['under']}</b>"


def format_markets(d: dict[str,Any]) -> list[str]:
    lines=["⏱ <b>1-Й ТАЙМ</b>",_fmt_total((d.get("first") or {}).get("main")),"🏁 <b>ВЕСЬ МАТЧ</b>",_fmt_total((d.get("full") or {}).get("main"))]
    ng=(d.get("full") or {}).get("next") or {}
    if ng:lines.append(f"🎯 Ещё 1 гол · ТБ {d.get('target')} <b>{(ng.get('over') or {}).get('C','—')}</b> · ТМ <b>{(ng.get('under') or {}).get('C','—')}</b>")
    b=d.get("btts") or {};lines.append(f"🤝 <b>ОБЕ ЗАБЬЮТ</b> · ДА <b>{(b.get('yes') or {}).get('C','—')}</b> · НЕТ <b>{(b.get('no') or {}).get('C','—')}</b>")
    n=d.get("next_goal") or {};lines.append(f"🥅 <b>СЛЕДУЮЩИЙ ГОЛ</b> · ДА/1 <b>{(n.get('yes') or {}).get('C','—')}</b> · НЕТ/2 <b>{(n.get('no') or {}).get('C','—')}</b>")
    raw=d.get("unknown_t910") or {}
    if raw:
        vals=[]
        for p,x in sorted(raw.items()):vals.append(f"P={p} T9={(x.get('over') or {}).get('C','—')} T10={(x.get('under') or {}).get('C','—')}")
        lines.append("🔬 <b>T9/T10 без scope:</b> <code>"+"; ".join(vals[:8])+"</code>")
    lines.append("⚠️ shadow: не влияет на CORE")
    return lines
