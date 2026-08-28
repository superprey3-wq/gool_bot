"""MonkeyBytes runtime: GOOL Market Server + PROGRUZ + BEST BET."""
from __future__ import annotations
import os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
HOME=Path(os.getenv("GOOL_HOME","/home/container"));BESTBET_DIR=HOME/"bestbet_runtime"
REPO="https://github.com/superprey3-wq/gool_bot.git";BESTBET_BRANCH="main"
COLLECTOR=HOME/"browser_market_node.py";ALL_COLLECTOR=HOME/"browser_market_all.py";PREMATCH=HOME/"prematch_market_node.py";FEED=HOME/"strong_proguz_feed.py";STORE=HOME/"market_store.py";STORE_BRIDGE=HOME/"market_store_bridge.py"
RAW_BASE="https://raw.githubusercontent.com/superprey3-wq/gool_bot/browser-market-node/"
def run(cmd,cwd=None,check=True):
 print("GOOL COMBINED exec:"," ".join(map(str,cmd)),flush=True);return subprocess.run(cmd,cwd=str(cwd) if cwd else None,check=check)
def sync_repo(path,branch):
 if (path/".git").exists():run(["git","fetch","origin",branch],cwd=path);run(["git","reset","--hard",f"origin/{branch}"],cwd=path)
 else:
  if path.exists():import shutil;shutil.rmtree(path,ignore_errors=True)
  run(["git","clone","--depth","1","--branch",branch,REPO,str(path)])
def sync_bestbet():sync_repo(BESTBET_DIR,BESTBET_BRANCH)
def sync_asset(name,path):
 try:
  data=urllib.request.urlopen(RAW_BASE+name,timeout=20).read();path.write_bytes(data);print(f"GOOL asset synced {name} bytes={len(data)}",flush=True)
 except Exception as e:
  print(f"GOOL asset sync failed {name}: {e}",flush=True)
  if not path.exists():raise
def install_requirements():
 seen=set()
 for req in (HOME/"requirements-browser-node.txt",BESTBET_DIR/"requirements.txt",BESTBET_DIR/"gool_bot"/"requirements.txt"):
  if req.exists() and str(req.resolve()) not in seen:seen.add(str(req.resolve()));run([sys.executable,"-m","pip","install","--user","-r",str(req)])
def child_env():
 env=os.environ.copy();env.setdefault("PYTHONUNBUFFERED","1");env.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json"));env.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history_v6.json"));env.setdefault("GOOL_MARKET_DB",str(HOME/"gool_market.sqlite3"));env.setdefault("GOOL_MARKET_STORE_POLL","5");env.setdefault("GOOL_MARKET_DB_RETENTION_SECONDS","21600");env.setdefault("GOOL_MARKET_ALL_MAX_EVENTS","250");env.setdefault("GOOL_MARKET_ALL_MAX_RECORDS","30000");env.setdefault("GOOL_MARKET_ALL_PER_EVENT","300");env.setdefault("GOOL_PREMATCH_STATE",str(HOME/"prematch_market_state.json"));env.setdefault("GOOL_PREMATCH_POLL_SECONDS","420");env.setdefault("GOOL_PREMATCH_MAX_FIXTURES","140");env.setdefault("GOOL_PREMATCH_ODDS_EVENTS","60");env.setdefault("GOOL_STRONG_MIN_SCORE","80");env.setdefault("GOOL_REMOTE_BEST_BET_STATE",str(HOME/"remote_best_bet_state.json"));env.setdefault("GOOL_REMOTE_BEST_BET_POLL_SECONDS","75");env.setdefault("SIGNAL_JOURNAL_FILE",str(HOME/"remote_best_bet_journal.json"));return env
def start(script,env,cwd=HOME):
 if not script.exists():raise FileNotFoundError(script)
 return subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(cwd),env=env)
def start_bestbet(env):return start(BESTBET_DIR/"gool_bot"/"best_bet_remote_worker.py",env,BESTBET_DIR/"gool_bot")
def stop(p):
 if p and p.poll() is None:
  try:p.terminate();p.wait(timeout=8)
  except Exception:
   try:p.kill()
   except Exception:pass
def main():
 print("GOOL MONKEY MARKET-SERVER+PROGRUZ+BEST-BET starting",flush=True)
 sync_bestbet()
 for name,path in (("browser_market_node.py",COLLECTOR),("browser_market_all.py",ALL_COLLECTOR),("prematch_market_node.py",PREMATCH),("strong_proguz_feed.py",FEED),("market_store.py",STORE),("market_store_bridge.py",STORE_BRIDGE)):sync_asset(name,path)
 install_requirements();env=child_env();live=start(ALL_COLLECTOR,env);prematch=start(PREMATCH,env);store=start(STORE_BRIDGE,env);bestbet=start_bestbet(env);feed=start(FEED,env);print(f"GOOL MONKEY ONLINE live={live.pid} prematch={prematch.pid} store={store.pid} bestbet={bestbet.pid} feed={feed.pid} sqlite=on strong>=80",flush=True)
 stopping=False
 def sig(*_):
  nonlocal stopping;stopping=True
 signal.signal(signal.SIGTERM,sig);signal.signal(signal.SIGINT,sig)
 try:
  while not stopping:
   for name,p,script,cwd in (("live",live,ALL_COLLECTOR,HOME),("prematch",prematch,PREMATCH,HOME),("store",store,STORE_BRIDGE,HOME),("bestbet",bestbet,BESTBET_DIR/"gool_bot"/"best_bet_remote_worker.py",BESTBET_DIR/"gool_bot"),("feed",feed,FEED,HOME)):
    if p.poll() is not None:
     print(f"GOOL MONKEY {name} exited rc={p.returncode}; supervisor restart required",flush=True);return
   time.sleep(3)
 finally:
  for p in (feed,bestbet,store,prematch,live):stop(p)
  print("GOOL MONKEY stopped",flush=True)
if __name__=="__main__":main()
