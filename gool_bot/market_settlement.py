"""Auditable settlement helpers for GOOL CORE full-time primary markets."""
from __future__ import annotations
from math import floor
from typing import Any

def parse_score(value:Any)->tuple[int,int]:
 try:a,b=str(value or "0:0").split(":",1);return int(a),int(b)
 except:return 0,0
def _over_legs(line:float)->list[float]:
 line=round(float(line),2);whole=floor(line);frac=round(line-whole,2)
 if frac==.25:return [float(whole),whole+.5]
 if frac==.75:return [whole+.5,float(whole+1)]
 return [line]
def over_pnl_units(line:float,odd:float,total_goals:int)->float:
 odd=float(odd)
 if odd<=1:raise ValueError("odd must be > 1.0")
 legs=_over_legs(line);pnl=0.;stake=1/len(legs)
 for leg in legs:
  pnl+=stake*(odd-1) if total_goals>leg else 0 if abs(total_goals-leg)<1e-9 else -stake
 return round(pnl,6)
def _kind(primary):return str(primary.get("market_type") or primary.get("market") or "TOTAL_OVER").upper()
def _result_from_pnl(pnl):return "+" if pnl>1e-9 else "-" if pnl<-1e-9 else "push"
def settle_primary(primary:dict[str,Any]|None,final_score:Any)->dict[str,Any]|None:
 if not isinstance(primary,dict):return None
 try:odd=float(primary["odd"])
 except (KeyError,TypeError,ValueError):return None
 h,a=parse_score(final_score);kind=_kind(primary)
 if kind=="BTTS":
  pnl=(odd-1) if h>0 and a>0 else -1.;return {"result":_result_from_pnl(pnl),"pnl_units":round(pnl,6),"settled_odd":odd,"settled_market":"BTTS","settled_total_goals":h+a}
 if kind in {"TEAM_TOTAL_HOME","TEAM_TOTAL_AWAY"}:
  try:line=float(primary["line"])
  except (KeyError,TypeError,ValueError):return None
  goals=h if kind.endswith("HOME") else a;pnl=over_pnl_units(line,odd,goals);return {"result":_result_from_pnl(pnl),"pnl_units":pnl,"settled_team_goals":goals,"settled_line":line,"settled_odd":odd,"settled_market":kind}
 if kind not in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER"}:return None
 try:line=float(primary["line"])
 except (KeyError,TypeError,ValueError):return None
 pnl=over_pnl_units(line,odd,h+a);return {"result":_result_from_pnl(pnl),"pnl_units":pnl,"settled_total_goals":h+a,"settled_line":line,"settled_odd":odd,"settled_market":"TOTAL_OVER"}
def fully_won_now(primary:dict[str,Any]|None,current_score:Any)->bool:
 if not isinstance(primary,dict):return False
 h,a=parse_score(current_score);kind=_kind(primary)
 if kind=="BTTS":return h>0 and a>0
 try:line=float(primary["line"])
 except (KeyError,TypeError,ValueError):return False
 if kind=="TEAM_TOTAL_HOME":total=h
 elif kind=="TEAM_TOTAL_AWAY":total=a
 elif kind in {"TOTAL","TOTAL_OVER","OVER_UNDER","OVER"}:total=h+a
 else:return False
 return all(total>leg for leg in _over_legs(line))
