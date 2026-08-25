"""Shared LIVE exposure/cadence gates for every GOOL strategy.

Football analytics decides whether a signal is good enough. This module only
controls *when* another signal may be opened on the same match:
- maximum two entries across CORE + auxiliary engines;
- only one still-open entry at a time;
- no new entries after minute 75;
- mandatory per-match cooldown between entries;
- after a confirmed result, cooldown restarts from the confirmation timestamp.
Odds/edge never participate in these gates.
"""
from __future__ import annotations
import os,time
from typing import Any

REAL_REASONS={"signal","reentry","first_half_goal","second_half_over15"}
PENDING_VALUES={"","pending","wait","waiting"}
MAX_MATCH_ENTRIES=2
MAX_OPEN_PER_MATCH=1
MAX_NEW_SIGNAL_MINUTE=75
MATCH_ENTRY_COOLDOWN_MINUTES=max(1,int(os.getenv("MATCH_ENTRY_COOLDOWN_MINUTES",os.getenv("LIVE_COOLDOWN_MINUTES","12"))))


def real_entries(rows:list[dict[str,Any]],event_id:str)->list[dict[str,Any]]:
    eid=str(event_id or "")
    return [r for r in rows if r.get("kind")=="live" and str(r.get("event_id") or "")==eid and str(r.get("reason") or "") in REAL_REASONS]


def _activity_ts(row:dict[str,Any])->int:
    """Latest meaningful timestamp for cadence.

    A fast goal must restart the waiting period; otherwise an entry opened long
    before the goal could immediately allow another signal after settlement.
    """
    vals=[]
    for key in ("created_ts","settled_ts","next_goal_confirmed_ts","result_ts","closed_ts"):
        try:
            v=int(float(row.get(key,0) or 0))
            if v>0:vals.append(v)
        except Exception:
            pass
    return max(vals) if vals else 0


def can_open(rows:list[dict[str,Any]],event_id:str,current_minute:int|None=None,now_ts:float|None=None)->tuple[bool,str]:
    entries=real_entries(rows,event_id)
    if current_minute is not None and int(current_minute or 0)>MAX_NEW_SIGNAL_MINUTE:
        return False,f"minute={int(current_minute or 0)}>{MAX_NEW_SIGNAL_MINUTE}"
    if len(entries)>=MAX_MATCH_ENTRIES:
        return False,f"max_entries={MAX_MATCH_ENTRIES}"
    pending=[r for r in entries if str(r.get("result") or "pending").strip().lower() in PENDING_VALUES]
    if len(pending)>=MAX_OPEN_PER_MATCH:
        return False,f"open_exposure={len(pending)}"
    if entries:
        latest=max(entries,key=_activity_ts)
        latest_ts=_activity_ts(latest)
        now=float(now_ts if now_ts is not None else time.time())
        required=MATCH_ENTRY_COOLDOWN_MINUTES*60
        elapsed=max(0,now-latest_ts) if latest_ts else required
        if elapsed<required:
            remain=max(1,int((required-elapsed+59)//60))
            return False,f"match_cooldown={remain}m"
        if current_minute is not None:
            try:last_minute=int(latest.get("minute") or 0)
            except Exception:last_minute=0
            if last_minute and int(current_minute or 0)<=last_minute:
                return False,f"same_match_minute={int(current_minute or 0)}<=last={last_minute}"
    return True,"ok"


def auditable_primary(primary:dict[str,Any]|None)->bool:
    if not isinstance(primary,dict):return False
    try:odd=float(primary["odd"])
    except (KeyError,TypeError,ValueError):return False
    if odd<=1:return False
    kind=str(primary.get("market_type") or primary.get("market") or "TOTAL_OVER").upper()
    if kind=="BTTS":return str(primary.get("scope") or "FULL_TIME")=="FULL_TIME"
    if kind in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER","TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"}:
        try:return bool(primary.get("scope")) and float(primary["line"])>=0
        except (KeyError,TypeError,ValueError):return False
    return False


def required_edge(reason:str)->float:return 0.0
def value_ok(primary:dict[str,Any]|None,reason:str)->tuple[bool,str]:return True,"odds_display_only"
