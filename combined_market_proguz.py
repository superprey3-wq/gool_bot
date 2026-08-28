"""MonkeyBytes runtime: market collectors + lightweight PROGRUZ feed + BEST BET.

The old full live-only-quant bot is intentionally NOT started here. PROGRUZ is
computed from browser_market_node state by strong_proguz_feed; Telegram delivery
remains on the main GOOL host. This avoids duplicating the full GOOL runtime and
keeps Monkey CPU comfortably below its 150% quota.
"""
from __future__ import annotations
import os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
HOME=Path(os.getenv("GOOL_HOME","/home/container"));BESTBET_DIR=HOME/"bestbet_runtime"
REPO="https://github.com/superprey3-wq/gool_bot.git";BESTBET_BRANCH="main"
COLLECTOR=HOME/"browser_market_node.py";PREMATCH=HOME/"prematch_market_node.py";FEED=HOME/"strong_proguz_feed.py"
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
 env=os.environ.copy();env.setdefault("PYTHONUNBUFFERED","1");env.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json"));env.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history_v6.json"));env.setdefault("GOOL_MARKET_MAX_EVENTS","100");env.setdefault("GOOL_MARKET_ODDS_EVENTS","24");env.setdefault("GOOL_PREMATCH_STATE",str(HOME/"prematch_market_state.json"));env.setdefault("GOOL_PREMATCH_POLL_SECONDS","420");env.setdefault("GOOL_PREMATCH_MAX_FIXTURES","140");env.setdefault("GOOL_PREMATCH_ODDS_EVENTS","60");env.setdefault("GOOL_STRONG_MIN_SCORE","80");env.setdefault("GOOL_REMOTE_BEST_BET_STATE",str(HOME/"remote_best_bet_state.json"));env.setdefault("GOOL_REMOTE_BEST_BET_POLL_SECONDS","75");env.setdefault("SIGNAL_JOURNAL_FILE",str(HOME/"remote_best_bet_journal.json"));return env
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
 print("GOOL MONKEY MARKET+PROGRUZ+BEST_BET starting",flush=True);sync_bestbet();sync_asset("prematch_market_node.py",PREMATCH);sync_asset("strong_proguz_feed.py",FEED);install_requirements();env=child_env();live=start(COLLECTOR,env);prematch=start(PREMATCH,env);bestbet=start_bestbet(env);feed=start(FEED,env);print(f"GOOL MONKEY ONLINE live_pid={live.pid} prematch_pid={prematch.pid} bestbet_pid={bestbet.pid} feed_pid={feed.pid} strong>=80 odds_events=24",flush=True)
 stopping=False
 def sig(*_):
  nonlocal stopping;stopping=True
 signal.signal(signal.SIGTERM,sig);signal.signal(signal.SIGINT,sig)
 try:
  while not stopping:
   if live.poll() is not None:print(f"GOOL MONKEY live exited rc={live.returncode}; restarting",flush=True);time.sleep(2);live=start(COLLECTOR,env)
   if prematch.poll() is not None:print(f"GOOL MONKEY prematch exited rc={prematch.returncode}; restarting",flush=True);time.sleep(2);prematch=start(PREMATCH,env)
   if bestbet.poll() is not None:print(f"GOOL MONKEY bestbet exited rc={bestbet.returncode}; restarting",flush=True);time.sleep(3);bestbet=start_bestbet(env)
   if feed.poll() is not None:print(f"GOOL MONKEY feed exited rc={feed.returncode}; restarting",flush=True);time.sleep(2);feed=start(FEED,env)
   time.sleep(3)
 finally:stop(feed);stop(bestbet);stop(prematch);stop(live);print("GOOL MONKEY stopped",flush=True)
if __name__=="__main__":main()
