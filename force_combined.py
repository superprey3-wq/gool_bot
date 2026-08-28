"""Single-file MonkeyBytes supervisor for GOOL market/proguz runtime.

Hosting panel should run this file directly. It does NOT import
combined_market_proguz.py, so there is no entrypoint chain to go stale.
"""
from __future__ import annotations
import os,signal,subprocess,sys,time,urllib.request
from pathlib import Path

BUILD="MONKEY-FLAT-2026-08-29-A"
HOME=Path(os.getenv("GOOL_HOME","/home/container"));BESTBET_DIR=HOME/"bestbet_runtime"
REPO="https://github.com/superprey3-wq/gool_bot.git";BESTBET_BRANCH="main"
LIVE=HOME/"browser_market_all.py";COLLECTOR=HOME/"browser_market_node.py";FEED=HOME/"strong_proguz_feed.py";STORE=HOME/"market_store.py";BRIDGE=HOME/"market_store_bridge.py";BETB2B=HOME/"betb2b_market_signal.py"
RAW_BASE="https://raw.githubusercontent.com/superprey3-wq/gool_bot/browser-market-node/"
OLD_RAW_BASE="https://raw.githubusercontent.com/superprey3-wq/gool_bot/live-only-quant-foundation/gool_bot/"

def run(cmd,cwd=None,check=True):
 print("GOOL exec:"," ".join(map(str,cmd)),flush=True);return subprocess.run(cmd,cwd=str(cwd) if cwd else None,check=check)

def sync_repo(path,branch):
 if (path/".git").exists():
  run(["git","fetch","origin",branch],cwd=path);run(["git","reset","--hard",f"origin/{branch}"],cwd=path)
 else:run(["git","clone","--depth","1","--branch",branch,REPO,str(path)])

def sync_asset(name,path,base=RAW_BASE):
 data=urllib.request.urlopen(base+name,timeout=20).read();path.write_bytes(data);print(f"GOOL asset {name} bytes={len(data)}",flush=True)

def env():
 e=os.environ.copy();e.setdefault("PYTHONUNBUFFERED","1");e.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json"));e.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history_v6.json"));e.setdefault("GOOL_MARKET_MAX_EVENTS","60");e.setdefault("GOOL_MARKET_ODDS_EVENTS","24");e.setdefault("GOOL_MARKET_MAX_RECORDS","1200");e.setdefault("GOOL_MARKET_PER_EVENT","140");e.setdefault("GOOL_STRONG_MIN_SCORE","80");e.setdefault("GOOL_BETB2B_POLL_SECONDS","45");e.setdefault("GOOL_REMOTE_BEST_BET_STATE",str(HOME/"remote_best_bet_state.json"));e.setdefault("GOOL_REMOTE_BEST_BET_POLL_SECONDS","75");e.setdefault("GOOL_MARKET_DB",str(HOME/"gool_market.sqlite3"));return e

def start(script,e,cwd=HOME):return subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(cwd),env=e)
def stop(p):
 if p and p.poll() is None:
  try:p.terminate();p.wait(timeout=6)
  except Exception:
   try:p.kill()
   except Exception:pass

def main():
 print(f"GOOL MONKEY FLAT ENTRY build={BUILD} file={Path(__file__).resolve()}",flush=True)
 print("GOOL MONKEY restoring old LIVE TOTAL PROGRUZ + BetB2B/1xBet",flush=True)
 sync_repo(BESTBET_DIR,BESTBET_BRANCH)
 for n,p in (("browser_market_node.py",COLLECTOR),("browser_market_all.py",LIVE),("strong_proguz_feed.py",FEED),("market_store.py",STORE),("market_store_bridge.py",BRIDGE)):sync_asset(n,p)
 sync_asset("betb2b_market_signal.py",BETB2B,OLD_RAW_BASE)
 e=env();spec={"live":(LIVE,HOME),"feed":(FEED,HOME),"store":(BRIDGE,HOME),"bestbet":(BESTBET_DIR/"gool_bot"/"best_bet_remote_worker.py",BESTBET_DIR/"gool_bot")}
 procs={name:start(script,e,cwd) for name,(script,cwd) in spec.items()}
 print("GOOL MONKEY ONLINE live_total_ou=on old_betb2b_1xbet=on proguz=on bestbet=on",flush=True)
 stopping=False
 def sig(*_):
  nonlocal stopping;stopping=True
 signal.signal(signal.SIGTERM,sig);signal.signal(signal.SIGINT,sig)
 try:
  while not stopping:
   for name,p in list(procs.items()):
    if p.poll() is not None:
     print(f"GOOL child {name} exited rc={p.returncode}; restarting in 5s",flush=True);time.sleep(5)
     script,cwd=spec[name]
     try:procs[name]=start(script,e,cwd);print(f"GOOL child {name} restarted pid={procs[name].pid}",flush=True)
     except Exception as exc:print(f"GOOL child {name} restart failed: {exc}",flush=True)
   time.sleep(3)
 finally:
  for p in procs.values():stop(p)
  print("GOOL MONKEY stopped",flush=True)

if __name__=="__main__":main()
