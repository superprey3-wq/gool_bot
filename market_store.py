"""Persistent normalized odds store for GOOL Market Server."""
from __future__ import annotations
import json,os,sqlite3,time
from pathlib import Path
DB=Path(os.getenv("GOOL_MARKET_DB","/home/container/gool_market.sqlite3"))

def connect():
 c=sqlite3.connect(DB,timeout=20);c.execute("PRAGMA journal_mode=WAL");c.execute("PRAGMA synchronous=NORMAL")
 c.executescript("""
 CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, ts REAL NOT NULL, source TEXT NOT NULL, complete INTEGER NOT NULL DEFAULT 1, records INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS odds(id INTEGER PRIMARY KEY, snapshot_id INTEGER NOT NULL, ts REAL NOT NULL, source TEXT NOT NULL, event_id TEXT, home TEXT, away TEXT, score TEXT, bookmaker TEXT, market TEXT, scope TEXT, line REAL, side TEXT, odd REAL, payload TEXT);
 CREATE INDEX IF NOT EXISTS ix_odds_event ON odds(event_id,ts DESC);
 CREATE INDEX IF NOT EXISTS ix_odds_teams ON odds(home,away,ts DESC);
 CREATE INDEX IF NOT EXISTS ix_odds_market ON odds(market,scope,ts DESC);
 """);return c

def ingest(records,source="flashscore_lsapp",ts=None):
 ts=float(ts or time.time()); rows=[r for r in records if isinstance(r,dict)]
 if not rows:return 0
 c=connect()
 try:
  cur=c.execute("INSERT INTO snapshots(ts,source,complete,records) VALUES(?,?,0,?)",(ts,source,len(rows)));sid=cur.lastrowid
  vals=[]
  for r in rows:
   vals.append((sid,ts,source,str(r.get("event_id") or ""),str(r.get("home") or ""),str(r.get("away") or ""),str(r.get("score") or ""),str(r.get("bookmaker") or r.get("bookmaker_id") or ""),str(r.get("market") or r.get("market_raw") or ""),str(r.get("scope") or "FULL_TIME"),r.get("line"),str(r.get("side") or r.get("selection") or ""),r.get("odd"),json.dumps(r,separators=(",",":"),ensure_ascii=False)))
  c.executemany("INSERT INTO odds(snapshot_id,ts,source,event_id,home,away,score,bookmaker,market,scope,line,side,odd,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",vals)
  c.execute("UPDATE snapshots SET complete=1 WHERE id=?",(sid,));c.commit()
  # bounded history: movement needs history, not an ever-growing DB
  cutoff=ts-float(os.getenv("GOOL_MARKET_DB_RETENTION_SECONDS","21600"));c.execute("DELETE FROM odds WHERE ts<?",(cutoff,));c.execute("DELETE FROM snapshots WHERE ts<?",(cutoff,));c.commit();return len(vals)
 finally:c.close()

def latest_records(max_age=300):
 c=connect()
 try:
  row=c.execute("SELECT id,ts FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone()
  if not row or time.time()-row[1]>max_age:return []
  return [json.loads(x[0]) for x in c.execute("SELECT payload FROM odds WHERE snapshot_id=?",(row[0],))]
 finally:c.close()

def health():
 c=connect()
 try:
  row=c.execute("SELECT ts,source,records FROM snapshots WHERE complete=1 ORDER BY ts DESC LIMIT 1").fetchone();return {"db":str(DB),"latest":None if not row else {"age":round(time.time()-row[0],1),"source":row[1],"records":row[2]}}
 finally:c.close()
