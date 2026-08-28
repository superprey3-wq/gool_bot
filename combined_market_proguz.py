"""MonkeyBytes combined runtime: lightweight market collector + GOOL PROGRUZ.

Runs the existing browser-market-node collector and a clean checkout of
live-only-quant-foundation on the same host. No browser/Chromium is used.
The supervisor restarts either child if it exits unexpectedly.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.getenv("GOOL_HOME", "/home/container"))
PROGUZ_DIR = HOME / "proguz_runtime"
REPO = "https://github.com/superprey3-wq/gool_bot.git"
PROGUZ_BRANCH = "live-only-quant-foundation"
COLLECTOR = HOME / "browser_market_node.py"


def run(cmd, cwd=None, check=True):
    print("GOOL COMBINED exec:", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check)


def sync_proguz():
    if (PROGUZ_DIR / ".git").exists():
        run(["git", "fetch", "origin", PROGUZ_BRANCH], cwd=PROGUZ_DIR)
        run(["git", "reset", "--hard", f"origin/{PROGUZ_BRANCH}"], cwd=PROGUZ_DIR)
    else:
        if PROGUZ_DIR.exists():
            import shutil
            shutil.rmtree(PROGUZ_DIR, ignore_errors=True)
        run(["git", "clone", "--depth", "1", "--branch", PROGUZ_BRANCH, REPO, str(PROGUZ_DIR)])


def install_requirements():
    reqs = [HOME / "requirements-browser-node.txt", PROGUZ_DIR / "requirements.txt", PROGUZ_DIR / "gool_bot" / "requirements.txt"]
    seen = set()
    for req in reqs:
        if req.exists() and str(req.resolve()) not in seen:
            seen.add(str(req.resolve()))
            run([sys.executable, "-m", "pip", "install", "--user", "-r", str(req)])


def child_env():
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    # Collector state is local on the same machine. PROGRUZ remains fully local;
    # a remote MARKET_NODE_URL is intentionally not required for this combined mode.
    env.setdefault("GOOL_MARKET_STATE", str(HOME / "market_node_state.json"))
    env.setdefault("GOOL_MARKET_HISTORY", str(HOME / "market_node_history_v6.json"))
    return env


def start_collector(env):
    if not COLLECTOR.exists():
        raise FileNotFoundError(COLLECTOR)
    return subprocess.Popen([sys.executable, "-u", str(COLLECTOR)], cwd=str(HOME), env=env)


def start_proguz(env):
    main = PROGUZ_DIR / "gool_bot" / "main.py"
    if not main.exists():
        raise FileNotFoundError(main)
    return subprocess.Popen([sys.executable, "-u", str(main)], cwd=str(main.parent), env=env)


def stop_child(p):
    if p and p.poll() is None:
        try:
            p.terminate(); p.wait(timeout=8)
        except Exception:
            try: p.kill()
            except Exception: pass


def main():
    print("GOOL COMBINED MARKET+PROGRUZ starting", flush=True)
    sync_proguz()
    install_requirements()
    env = child_env()
    collector = start_collector(env)
    proguz = start_proguz(env)
    print(f"GOOL COMBINED ONLINE collector_pid={collector.pid} proguz_pid={proguz.pid}", flush=True)

    stopping = False
    def _stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        while not stopping:
            if collector.poll() is not None:
                print(f"GOOL COMBINED collector exited rc={collector.returncode}; restarting", flush=True)
                time.sleep(2)
                collector = start_collector(env)
            if proguz.poll() is not None:
                print(f"GOOL COMBINED proguz exited rc={proguz.returncode}; restarting", flush=True)
                time.sleep(3)
                proguz = start_proguz(env)
            time.sleep(3)
    finally:
        stop_child(proguz)
        stop_child(collector)
        print("GOOL COMBINED stopped", flush=True)


if __name__ == "__main__":
    main()
