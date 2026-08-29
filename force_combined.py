"""MonkeyBytes single-root supervisor for PROGRUZ + remote BEST BET."""
from __future__ import annotations
import os,signal,subprocess,sys,time
from pathlib import Path
BUILD="MONKEY-OLD-PROGRUZ-2026-08-29-D"
HOME=Path(os.getenv("GOOL_HOME","/home/container"));BESTBET_DIR=HOME/"bestbet_runtime";REPO="https://github.com/superprey3-wq/gool_bot.git";BESTBET_BRANCH="main"
LIVE=HOME/"browser_market_all.py";FEED=HOME/"strong_proguz_feed.py";BRIDGE=HOME/"market_store_bridge.py"
def run(cmd,cwd=None):print("GOOL exec:"," ".join(map(str,cmd)),flush=True);return subprocess.run(cmd,cwd=str(cwd) if cwd else None,check=True)
def sync_bestbet():
 if (BESTBET_DIR/".git").exists():run(["git","fetch","origin",BESTBET_BRANCH],BESTBET_DIR);run(["git","reset","--hard",f"origin/{BESTBET_BRANCH}"],BESTBET_DIR)
 else:run(["git","clone","--depth","1","--branch",BESTBET_BRANCH,REPO,str(BESTBET_DIR)])
def env():
 e=os.environ.copy();e.setdefault("PYTHONUNBUFFERED","1");e.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json"));e.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history.json"));e["GOOL_MARKET_MAX_EVENTS"]="100";e["GOOL_MARKET_ODDS_EVENTS"]="100";e.setdefault("GOOL_MARKET_MAX_RECORDS","2400");e.setdefault("GOOL_MARKET_PER_EVENT","160");e.setdefault("GOOL_STRONG_MIN_SCORE","80");e.setdefault("GOOL_BETB2B_POLL_SECONDS","45");e.setdefault("GOOL_REMOTE_BEST_BET_STATE",str(HOME/"remote_best_bet_state.json"));e.setdefault("GOOL_REMOTE_BEST_BET_POLL_SECONDS","75");e.setdefault("GOOL_MARKET_DB",str(HOME/"gool_market.sqlite3"));return e
def start(script,e,cwd=HOME):return subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(cwd),env=e)
def stop(p):
 if p and p.poll() is None:
  try:p.terminate();p.wait(timeout=6)
  except Exception:
   try:p.kill()
   except Exception:pass
def main():
 print(f"GOOL MONKEY ROOT ENTRY build={BUILD} file={Path(__file__).resolve()}",flush=True);sync_bestbet();e=env();spec={"live":(LIVE,HOME),"feed":(FEED,HOME),"store":(BRIDGE,HOME),"bestbet":(BESTBET_DIR/"gool_bot"/"best_bet_remote_worker.py",BESTBET_DIR/"gool_bot")};procs={n:start(s,e,c) for n,(s,c) in spec.items()};print("GOOL MONKEY ONLINE old_sources=LSApp+BetB2B/1xBet+Kambi all_live=on proguz=on bestbet=on",flush=True);stopping=False
 def sig(*_):
  nonlocal stopping;stopping=True
 signal.signal(signal.SIGTERM,sig);signal.signal(signal.SIGINT,sig)
 try:
  while not stopping:
   for n,p in list(procs.items()):
    if p.poll() is not None:
     print(f"GOOL child {n} exited rc={p.returncode}; restarting in 5s",flush=True);time.sleep(5);s,c=spec[n];procs[n]=start(s,e,c)
   time.sleep(3)
 finally:
  for p in procs.values():stop(p)
if __name__=="__main__":main()
