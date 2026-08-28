"""MonkeyBytes combined runtime: live market + prematch market + GOOL PROGRUZ."""
from __future__ import annotations
import os, signal, subprocess, sys, time
from pathlib import Path
HOME=Path(os.getenv("GOOL_HOME","/home/container"))
PROGUZ_DIR=HOME/"proguz_runtime"
REPO="https://github.com/superprey3-wq/gool_bot.git"
PROGUZ_BRANCH="live-only-quant-foundation"
COLLECTOR=HOME/"browser_market_node.py"
PREMATCH=HOME/"prematch_market_node.py"

def run(cmd,cwd=None,check=True):
    print("GOOL COMBINED exec:"," ".join(map(str,cmd)),flush=True)
    return subprocess.run(cmd,cwd=str(cwd) if cwd else None,check=check)

def sync_proguz():
    if (PROGUZ_DIR/".git").exists():
        run(["git","fetch","origin",PROGUZ_BRANCH],cwd=PROGUZ_DIR); run(["git","reset","--hard",f"origin/{PROGUZ_BRANCH}"],cwd=PROGUZ_DIR)
    else:
        if PROGUZ_DIR.exists():
            import shutil; shutil.rmtree(PROGUZ_DIR,ignore_errors=True)
        run(["git","clone","--depth","1","--branch",PROGUZ_BRANCH,REPO,str(PROGUZ_DIR)])

def install_requirements():
    seen=set()
    for req in (HOME/"requirements-browser-node.txt",PROGUZ_DIR/"requirements.txt",PROGUZ_DIR/"gool_bot"/"requirements.txt"):
        if req.exists() and str(req.resolve()) not in seen:
            seen.add(str(req.resolve())); run([sys.executable,"-m","pip","install","--user","-r",str(req)])

def child_env():
    env=os.environ.copy(); env.setdefault("PYTHONUNBUFFERED","1")
    env.setdefault("GOOL_MARKET_STATE",str(HOME/"market_node_state.json")); env.setdefault("GOOL_MARKET_HISTORY",str(HOME/"market_node_history_v6.json"))
    env.setdefault("GOOL_PREMATCH_STATE",str(HOME/"prematch_market_state.json")); env.setdefault("GOOL_PREMATCH_POLL_SECONDS","300")
    env.setdefault("GOOL_PREMATCH_MAX_FIXTURES","220"); env.setdefault("GOOL_PREMATCH_ODDS_EVENTS","100")
    return env

def start(script,env,cwd=HOME):
    if not script.exists(): raise FileNotFoundError(script)
    return subprocess.Popen([sys.executable,"-u",str(script)],cwd=str(cwd),env=env)
def start_proguz(env): return start(PROGUZ_DIR/"gool_bot"/"main.py",env,PROGUZ_DIR/"gool_bot")
def stop(p):
    if p and p.poll() is None:
        try: p.terminate(); p.wait(timeout=8)
        except Exception:
            try: p.kill()
            except Exception: pass

def main():
    print("GOOL COMBINED LIVE+PREMATCH+PROGRUZ starting",flush=True); sync_proguz(); install_requirements(); env=child_env()
    live=start(COLLECTOR,env); prematch=start(PREMATCH,env); proguz=start_proguz(env)
    print(f"GOOL COMBINED ONLINE live_pid={live.pid} prematch_pid={prematch.pid} proguz_pid={proguz.pid} schedule=today+tomorrow odds=on",flush=True)
    stopping=False
    def sig(*_):
        nonlocal stopping; stopping=True
    signal.signal(signal.SIGTERM,sig); signal.signal(signal.SIGINT,sig)
    try:
        while not stopping:
            if live.poll() is not None: print(f"GOOL COMBINED live exited rc={live.returncode}; restarting",flush=True); time.sleep(2); live=start(COLLECTOR,env)
            if prematch.poll() is not None: print(f"GOOL COMBINED prematch exited rc={prematch.returncode}; restarting",flush=True); time.sleep(2); prematch=start(PREMATCH,env)
            if proguz.poll() is not None: print(f"GOOL COMBINED proguz exited rc={proguz.returncode}; restarting",flush=True); time.sleep(3); proguz=start_proguz(env)
            time.sleep(3)
    finally:
        stop(proguz); stop(prematch); stop(live); print("GOOL COMBINED stopped",flush=True)
if __name__=="__main__": main()
