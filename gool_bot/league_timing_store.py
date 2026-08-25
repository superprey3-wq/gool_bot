"""Compact persistent goal-timing profiles by competition.

Only aggregates are retained on the runtime VPS. Historical importers should
stream matches through add_match(); raw matches are never kept in memory or on
disk here. A tiny rolling fingerprint list prevents immediate duplicate writes.
"""
from __future__ import annotations
import hashlib,json,os,re,time
from pathlib import Path

STORE=Path(os.getenv("LEAGUE_TIMING_STORE","league_timing.json"))
BINS=((1,15),(16,30),(31,45),(46,60),(61,75),(76,90),(91,130))
DEDUPE_KEEP=int(os.getenv("LEAGUE_TIMING_DEDUPE_KEEP","128"))


def norm(name:str)->str:
    return " ".join(re.sub(r"[^a-z0-9]+"," ",str(name or "").lower()).split())

def _load()->dict:
    try:
        d=json.loads(STORE.read_text("utf-8"));return d if isinstance(d,dict) else {}
    except Exception:return {}

def _save(d:dict)->None:
    tmp=STORE.with_suffix(STORE.suffix+".tmp")
    tmp.write_text(json.dumps(d,ensure_ascii=False,separators=(",",":")),"utf-8");tmp.replace(STORE)

def _minute(v)->int|None:
    try:
        s=str(v).strip().replace("’","").replace("'","")
        if "+" in s:
            a,b=s.split("+",1);return int(a)+int(re.sub(r"\D","",b) or 0)
        return int(re.sub(r"\D","",s) or 0)
    except Exception:return None

def _fingerprint(competition,season,match_id,goal_minutes):
    raw=f"{norm(competition)}|{season}|{match_id}|{','.join(map(str,goal_minutes or []))}"
    return hashlib.blake2s(raw.encode("utf-8"),digest_size=6).hexdigest()

def add_match(competition:str,goal_minutes,source="runtime",season="",match_id="")->dict:
    key=norm(competition)
    if not key:return {}
    data=_load();row=data.setdefault(key,{"competition":competition,"matches":0,"goals":0,"bins":[0]*7,"source_counts":{},"seasons":{},"recent_fp":[],"updated_at":0})
    fp=_fingerprint(competition,season,match_id,goal_minutes);seen=list(row.get("recent_fp") or [])[-DEDUPE_KEEP:]
    if fp in seen:return row
    mins=[m for m in (_minute(x) for x in (goal_minutes or [])) if m is not None and m>0]
    row["matches"]=int(row.get("matches",0))+1;row["goals"]=int(row.get("goals",0))+len(mins)
    bins=(list(row.get("bins") or [])+[0]*7)[:7]
    for minute in mins:
        idx=6
        for i,(lo,hi) in enumerate(BINS):
            if lo<=minute<=hi:idx=i;break
        bins[idx]+=1
    row["bins"]=bins
    src=row.setdefault("source_counts",{});src[source]=int(src.get(source,0))+1
    if season:
        ss=row.setdefault("seasons",{});ss[str(season)]=int(ss.get(str(season),0))+1
        # retain only the latest handful of season labels; aggregates remain cumulative
        if len(ss)>8:
            for old in list(ss)[:-8]:ss.pop(old,None)
    seen.append(fp);row["recent_fp"]=seen[-DEDUPE_KEEP:]
    row["updated_at"]=int(time.time());_save(data);return row

def profile(competition:str)->dict:
    row=_load().get(norm(competition)) or {}
    n=int(row.get("matches",0) or 0);goals=int(row.get("goals",0) or 0);bins=(list(row.get("bins") or [])+[0]*7)[:7]
    if not n:return {}
    fh=sum(bins[:3]);late=bins[5]+bins[6]
    return {"matches":n,"goals":goals,"goals_per_match":round(goals/n,3),"first_half_goals_per_match":round(fh/n,3),"late_goals_per_match":round(late/n,3),"late_goal_share":round(late/max(1,goals),4),"bins":bins,"source_counts":row.get("source_counts",{}),"updated_at":row.get("updated_at",0)}
