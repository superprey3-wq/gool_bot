"""MonkeyBytes runtime: restored lightweight PROGRUZ + remote BEST BET.

The Flashscore/LSApp JSON state is the critical path again. Optional persistence
and BEST BET cannot stop the live collector/feed. Every child is restarted in
place instead of taking the whole Monkey server offline.
"""
from __future__ import annotations
import os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
HOME=Path(os.getenv("GOOL_HOME","/home/container"));BESTBET_DIR=HOME/"bestbet_runtime"
REPO="https://github.com/superprey3-wq/gool_bot.git";BESTBET_BRANCH="main"
LIVE=HOME/"browser_market_all.py";COLLECTOR=HOME/"browser_market_node.py";FEED=HOME/"strong_proguz_feed.py";STORE=HOME/"market_store.py";BRIDGE=HOME/"market_store_bridge.py"
RAW_BASE="https://raw.githubusercontent.com/superprey3-wq/gool_bot/browser-market-node/"
def run(cmd,cwd=None,check=True):print("GOOL exec:"," ".join(map(str,cmd)),flush=True);return subprocess.run(cmd,cwd=str(cwd) if cwd else None,check=check)
def sync_repo(path,branch):
 if (path/".git").exists():run(["git","fetch","origin",branch],cwd=path);run(["git","reset","--hard",f"origin/{branch}"],cwd=path)
 else:run(["git","clone","--depth","1","--branch",branch,REPO,str(path)])
def sync_asset(name,path):
 data=urllib.request.urlopen(RAW_BASE+name,timeout=20).read();path.write_bytes(data);print(f"GOOL asset {name} bytes={len(data)}",flush=True)
def env():
 e=os.environ.copy();e.setdefault("PYTHONUNBUFFERED","1");e.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json"));e.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history_v6.json"));e.setdefault("GOOL_MARKET_MAX_EVENTS","60");e.setdefault("GOOL_MARKET_ODDS_EVENTS","12");e.setdefault("GOOL_MARKET_MAX_RECORDS","1800");e.setdefault("GOOL_MARKET_PER_EVENT","260");e.setdefault("GOOL_STRONG_MIN_SCORE","80");e.setdefault("GOOL_REMOTE_BEST_BET_STATE",str(HOME/"remote_best_bet_state.json"));e.setdefault("GOOL_REMOTE_BEST_BET_POLL_SECONDS","75");e.setdefault("GOOL_MARKET_DB",str(HOME/"gool_market.sqlite3"));return e
def start(script,e,cwd=HOME):return subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(cwd),env=e)
def stop(p):
 if p and p.poll() is None:
  try:p.terminate();p.wait(timeout=6)
  except Exception:
   try:p.kill()
   except Exception:pass
def main():
 print("GOOL MONKEY restoring proven PROGRUZ pipeline",flush=True)
 sync_repo(BESTBET_DIR,BESTBET_BRANCH)
 for n,p in (("browser_market_node.py",COLLECTOR),("browser_market_all.py",LIVE),("strong_proguz_feed.py",FEED),("market_store.py",STORE),("market_store_bridge.py",BRIDGE)):sync_asset(n,p)
 e=env();spec={"live":(LIVE,HOME),"feed":(FEED,HOME),"store":(BRIDGE,HOME),"bestbet":(BESTBET_DIR/"gool_bot"/"best_bet_remote_worker.py",BESTBET_DIR/"gool_bot")}
 procs={name:start(script,e,cwd) for name,(script,cwd) in spec.items()}
 print("GOOL MONKEY ONLINE stable-live=on proguz=on bestbet=on sqlite=aux",flush=True)
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
