"""Persistent goal-timing profiles by competition.

The store is source-agnostic: historical backfills (Flashscore/StatBunker/
open datasets) and GOOL live settlements can feed the same schema.
"""
from __future__ import annotations
import json,os,re,time
from pathlib import Path

STORE=Path(os.getenv("LEAGUE_TIMING_STORE","league_timing.json"))
BINS=((1,15),(16,30),(31,45),(46,60),(61,75),(76,90),(91,130))


def norm(name:str)->str:
    return " ".join(re.sub(r"[^a-z0-9]+"," ",str(name or "").lower()).split())


def _load()->dict:
    try:
        d=json.loads(STORE.read_text("utf-8"));return d if isinstance(d,dict) else {}
    except Exception:return {}


def _save(d:dict)->None:
    tmp=STORE.with_suffix(STORE.suffix+".tmp")
    tmp.write_text(json.dumps(d,ensure_ascii=False,sort_keys=True),"utf-8");tmp.replace(STORE)


def _minute(v)->int|None:
    try:
        s=str(v).strip().replace("’","").replace("'","")
        if "+" in s:
            a,b=s.split("+",1);return int(a)+int(re.sub(r"\D","",b) or 0)
        return int(re.sub(r"\D","",s) or 0)
    except Exception:return None


def add_match(competition:str,goal_minutes,source="runtime",season="",match_id="")->dict:
    key=norm(competition)
    if not key:return {}
    data=_load();row=data.setdefault(key,{"competition":competition,"matches":0,"goals":0,"bins":[0]*7,"source_counts":{},"seasons":{},"updated_at":0})
    # Optional dedupe for imported/runtime event ids.
    seen=row.setdefault("match_ids",[])
    mid=str(match_id or "")
    if mid and mid in seen:return row
    mins=[m for m in (_minute(x) for x in (goal_minutes or [])) if m is not None and m>0]
    row["matches"]=int(row.get("matches",0))+1;row["goals"]=int(row.get("goals",0))+len(mins)
    bins=list(row.get("bins") or [0]*7);bins=(bins+[0]*7)[:7]
    for minute in mins:
        idx=6
        for i,(lo,hi) in enumerate(BINS):
            if lo<=minute<=hi:idx=i;break
        bins[idx]+=1
    row["bins"]=bins;src=row.setdefault("source_counts",{});src[source]=int(src.get(source,0))+1
    if season:
        ss=row.setdefault("seasons",{});ss[str(season)]=int(ss.get(str(season),0))+1
    if mid:
        seen.append(mid);row["match_ids"]=seen[-5000:]
    row["updated_at"]=int(time.time());_save(data);return row


def profile(competition:str)->dict:
    row=_load().get(norm(competition)) or {}
    n=int(row.get("matches",0) or 0);goals=int(row.get("goals",0) or 0);bins=list(row.get("bins") or [0]*7);bins=(bins+[0]*7)[:7]
    if not n:return {}
    fh=sum(bins[:3]);late=bins[5]+bins[6]
    return {"matches":n,"goals":goals,"goals_per_match":round(goals/n,3),"first_half_goals_per_match":round(fh/n,3),"late_goals_per_match":round(late/n,3),"late_goal_share":round(late/max(1,goals),4),"bins":bins,"source_counts":row.get("source_counts",{}),"updated_at":row.get("updated_at",0)}
