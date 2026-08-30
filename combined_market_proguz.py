"""MonkeyBytes all-in-one runtime: GOOL MAIN V3 + market history + strong PROGRUZ."""
from __future__ import annotations
import os,signal,subprocess,sys,time,urllib.request
from pathlib import Path

HOME=Path(os.getenv("GOOL_HOME","/home/container"))
MAIN_DIR=HOME/"main_runtime"
REPO="https://github.com/superprey3-wq/gool_bot.git"
MAIN_BRANCH="main"
LIVE=HOME/"browser_market_all.py";PREMATCH=HOME/"prematch_market_collector.py";COLLECTOR=HOME/"browser_market_node.py";FEED_BASE=HOME/"strong_proguz_feed.py";FEED_V11=HOME/"strong_proguz_v9.py";FEED=HOME/"strong_proguz_v12.py";FLOW=HOME/"proguz_market_flow.py";FAIR=HOME/"proguz_fair_probability.py";BRIDGE=HOME/"market_store_bridge.py";BETB2B=HOME/"betb2b_market_signal.py";CONTEXT=HOME/"monkey_live_context.py"
RAW_BASE="https://raw.githubusercontent.com/superprey3-wq/gool_bot/browser-market-node/";OLD_RAW_BASE="https://raw.githubusercontent.com/superprey3-wq/gool_bot/live-only-quant-foundation/gool_bot/"

def run(cmd,cwd=None,check=True):
 print("GOOL exec:"," ".join(map(str,cmd)),flush=True)
 return subprocess.run(cmd,cwd=str(cwd) if cwd else None,check=check)

def sync_repo(path,branch):
 if (path/".git").exists():
  run(["git","fetch","origin",branch],cwd=path)
  run(["git","reset","--hard",f"origin/{branch}"],cwd=path)
 else:
  run(["git","clone","--depth","1","--branch",branch,REPO,str(path)])

def sync_asset(name,path,base=RAW_BASE):
 data=urllib.request.urlopen(base+name,timeout=20).read();path.write_bytes(data);print(f"GOOL asset {name} bytes={len(data)}",flush=True)

def env():
 e=os.environ.copy();e.setdefault("PYTHONUNBUFFERED","1")
 # Shared market/proguz state.
 e.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json"));e.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history_v6.json"));e.setdefault("GOOL_MARKET_MAX_EVENTS","100");e.setdefault("GOOL_MARKET_ODDS_EVENTS","40");e.setdefault("GOOL_MARKET_MAX_RECORDS","1600");e.setdefault("GOOL_MARKET_PER_EVENT","160");e.setdefault("GOOL_STRONG_MIN_SCORE","80");e.setdefault("GOOL_BETB2B_POLL_SECONDS","45");e.setdefault("GOOL_MARKET_DB",str(HOME/"gool_market.sqlite3"));e.setdefault("GOOL_MARKET_DB_RETENTION_SECONDS","43200")
 e.setdefault("GOOL_PREMATCH_HORIZON_HOURS","6");e.setdefault("GOOL_PREMATCH_POLL_SECONDS","120");e.setdefault("GOOL_PREMATCH_MAX_EVENTS","60")
 e.setdefault("GOOL_MONKEY_LIVE_CONTEXT",str(HOME/"monkey_live_context.json"));e.setdefault("GOOL_MONKEY_LIVE_POLL_SECONDS","20")
 e.setdefault("GOOL_PROGRUZ_FLOW_LOOKBACK_SECONDS","900");e.setdefault("GOOL_PROGRUZ_MIN_FAIR_MOVE_PP","1.0");e.setdefault("GOOL_PROGRUZ_SECOND_CONFIRM_MOVE","0.8");e.setdefault("GOOL_PROGRUZ_CUM_FAIR_MOVE_PP","1.5");e.setdefault("GOOL_PROGRUZ_CUM_FLOW_SCORE","64");e.setdefault("GOOL_PROGRUZ_CUM_PERSISTENCE","0.45");e.setdefault("GOOL_PROGRUZ_AUDIT",str(HOME/"proguz_v11_audit.jsonl"))
 # MAIN bot runtime state lives outside the git checkout and survives git reset.
 e.setdefault("SIGNAL_JOURNAL_FILE",str(HOME/"signal_journal.json"));e.setdefault("LIVE_STATE_FILE",str(HOME/"live_state.json"));e.setdefault("LIVE_SENT_STATE_FILE",str(HOME/"live_sent.json"));e.setdefault("TELEGRAM_SUBSCRIBERS_FILE",str(HOME/"telegram_subscribers.json"));e.setdefault("GOOL_STRONG_FEED_SENT",str(HOME/"strong_proguz_sent.json"));e.setdefault("GOOL_STRONG_FEED_URL","http://127.0.0.1:5056/strong")
 e.setdefault("LIVE_SIGNAL_THRESHOLD","80");e.setdefault("LIVE_COOLDOWN_MINUTES","12");e.setdefault("LIVE_INTERVAL_SECONDS","60")
 return e

def start(script,e,cwd=HOME):return subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(cwd),env=e)
def stop(p):
 if p and p.poll() is None:
  try:p.terminate();p.wait(timeout=8)
  except Exception:
   try:p.kill()
   except Exception:pass

def main():
 print("GOOL MONKEY ALL-IN-ONE | MAIN V3 FT+1H+2H + PREMATCH/LIVE MARKET + STRONG PROGRUZ V12 | BEST BET=OFF",flush=True)
 sync_repo(MAIN_DIR,MAIN_BRANCH)
 for n,p in (("browser_market_node.py",COLLECTOR),("browser_market_all.py",LIVE),("prematch_market_collector.py",PREMATCH),("strong_proguz_feed.py",FEED_BASE),("strong_proguz_v9.py",FEED_V11),("strong_proguz_v12.py",FEED),("proguz_market_flow.py",FLOW),("proguz_fair_probability.py",FAIR),("market_store_bridge.py",BRIDGE),("monkey_live_context.py",CONTEXT)):sync_asset(n,p)
 sync_asset("betb2b_market_signal.py",BETB2B,OLD_RAW_BASE)
 e=env();main_cwd=MAIN_DIR/"gool_bot"
 spec={"context":(CONTEXT,HOME),"prematch":(PREMATCH,HOME),"live":(LIVE,HOME),"feed":(FEED,HOME),"store":(BRIDGE,HOME),"main":(main_cwd/"main.py",main_cwd)}
 procs={name:start(script,e,cwd) for name,(script,cwd) in spec.items()}
 print("GOOL MONKEY ONLINE main_v3=on systems=FT+1H+2H telegram=on journal=shared strong_proguz=on prematch=on live_market=on bestbet=off strong_feed=localhost",flush=True)
 stopping=False
 def sig(*_):
  nonlocal stopping;stopping=True
 signal.signal(signal.SIGTERM,sig);signal.signal(signal.SIGINT,sig)
 try:
  while not stopping:
   for name,p in list(procs.items()):
    if p.poll() is not None:
     print(f"GOOL child {name} exited rc={p.returncode}; restarting in 5s",flush=True);time.sleep(5);script,cwd=spec[name]
     # Refresh MAIN code before restarting it after a crash/update.
     if name=="main":
      try:sync_repo(MAIN_DIR,MAIN_BRANCH)
      except Exception as exc:print(f"GOOL main repo refresh failed: {exc}",flush=True)
     try:procs[name]=start(script,e,cwd);print(f"GOOL child {name} restarted pid={procs[name].pid}",flush=True)
     except Exception as exc:print(f"GOOL child {name} restart failed: {exc}",flush=True)
   time.sleep(3)
 finally:
  for p in procs.values():stop(p)
  print("GOOL MONKEY stopped",flush=True)
if __name__=="__main__":main()
