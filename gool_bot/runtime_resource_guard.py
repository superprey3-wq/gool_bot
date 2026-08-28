"""Tiny Linux resource guard for low-memory bot hosting.

Uses /proc only; adds no dependency.  It reports process RSS/system memory and
lets optional work fail open/closed without killing the production loop.
"""
from __future__ import annotations
import logging,os
log=logging.getLogger("runtime_resource_guard")

def _kb_from(path,key):
 try:
  for line in open(path,"r",encoding="utf-8"):
   if line.startswith(key+":"):return int(line.split()[1])
 except Exception:pass
 return 0

def snapshot():
 total=_kb_from("/proc/meminfo","MemTotal");avail=_kb_from("/proc/meminfo","MemAvailable");rss=_kb_from("/proc/self/status","VmRSS")
 try:load1=os.getloadavg()[0]
 except Exception:load1=0.0
 cpu=os.cpu_count() or 1
 return {"mem_total_mb":round(total/1024,1),"mem_available_mb":round(avail/1024,1),"rss_mb":round(rss/1024,1),"load1":round(load1,2),"cpu_count":cpu,"load_ratio":round(load1/cpu,2)}

def allow_optional(min_available_mb=90,max_rss_mb=420,max_load_ratio=1.8):
 s=snapshot()
 if s["mem_available_mb"] and s["mem_available_mb"]<min_available_mb:return False,s,"low_available_memory"
 if s["rss_mb"] and s["rss_mb"]>max_rss_mb:return False,s,"high_process_rss"
 if s["load_ratio"]>max_load_ratio:return False,s,"high_cpu_load"
 return True,s,"ok"

def log_startup():
 s=snapshot();log.info("RESOURCE rss=%.1fMB available=%.1fMB total=%.1fMB cpu=%d load1=%.2f ratio=%.2f",s['rss_mb'],s['mem_available_mb'],s['mem_total_mb'],s['cpu_count'],s['load1'],s['load_ratio']);return s
