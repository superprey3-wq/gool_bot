"""Deprecated compatibility shim: Bovada is disabled in GOOL production.

Flashscore/LSApp is the primary LIVE market source. This module intentionally
returns no prices so legacy imports cannot reintroduce Bovada into signal logic.
"""
from __future__ import annotations

_CACHE_TTL=0

def invalidate_live_cache():return None
def _find_event(*args,**kwargs):return None
def _over_prices(*args,**kwargs):return {}
def _ratio(*args,**kwargs):return 0.0
def get_all_full_time_over_odds(*args,**kwargs):return []
def get_goal_total_odds(*args,**kwargs):return []
def get_first_half_total_odds(*args,**kwargs):return []
def get_second_half_over15(*args,**kwargs):return None
def get_first_half_goal_odds(*args,**kwargs):return None
def get_first_half_over05(*args,**kwargs):return None
def get_btts_yes(*args,**kwargs):return None
