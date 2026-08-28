"""MonkeyBytes single-root supervisor.

Runs only files from /home/container. Legacy proguz_runtime checkout is disabled
so it cannot shadow the active browser-market-node code.
"""
from __future__ import annotations
import os, signal, subprocess, sys, time
from pathlib import Path

BUILD = "MONKEY-ROOT-2026-08-29-C"
HOME = Path(os.getenv("GOOL_HOME", "/home/container"))
BESTBET_DIR = HOME / "bestbet_runtime"
LEGACY_PROGUZ = HOME / "proguz_runtime"
LEGACY_DISABLED = HOME / "proguz_runtime.disabled"
REPO = "https://github.com/superprey3-wq/gool_bot.git"
BESTBET_BRANCH = "main"

LIVE = HOME / "browser_market_all.py"
COLLECTOR = HOME / "browser_market_node.py"
FEED = HOME / "strong_proguz_feed.py"
BRIDGE = HOME / "market_store_bridge.py"
BETB2B = HOME / "betb2b_market_signal.py"


def run(cmd, cwd=None, check=True):
    print("GOOL exec:", " ".join(map(str, cmd)), flush=True)
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=check)


def sync_bestbet():
    if (BESTBET_DIR / ".git").exists():
        run(["git", "fetch", "origin", BESTBET_BRANCH], cwd=BESTBET_DIR)
        run(["git", "reset", "--hard", f"origin/{BESTBET_BRANCH}"], cwd=BESTBET_DIR)
    else:
        run(["git", "clone", "--depth", "1", "--branch", BESTBET_BRANCH, REPO, str(BESTBET_DIR)])


def disable_legacy_proguz():
    if not LEGACY_PROGUZ.exists():
        print("GOOL legacy proguz_runtime=absent", flush=True)
        return
    try:
        if LEGACY_DISABLED.exists():
            print("GOOL legacy proguz_runtime already has disabled copy; leaving active path untouched", flush=True)
            return
        LEGACY_PROGUZ.rename(LEGACY_DISABLED)
        print(f"GOOL legacy proguz_runtime DISABLED -> {LEGACY_DISABLED}", flush=True)
    except Exception as exc:
        print(f"GOOL legacy proguz_runtime disable failed: {exc}", flush=True)


def env():
    e = os.environ.copy()
    e.setdefault("PYTHONUNBUFFERED", "1")
    e.setdefault("GOOL_MARKET_STATE", str(HOME / "market_node_state.json"))
    e.setdefault("GOOL_MARKET_HISTORY", str(HOME / "market_node_history.json"))
    e.setdefault("GOOL_MARKET_MAX_EVENTS", "60")
    e.setdefault("GOOL_MARKET_ODDS_EVENTS", "24")
    e.setdefault("GOOL_MARKET_MAX_RECORDS", "1200")
    e.setdefault("GOOL_MARKET_PER_EVENT", "140")
    e.setdefault("GOOL_STRONG_MIN_SCORE", "80")
    e.setdefault("GOOL_BETB2B_POLL_SECONDS", "45")
    e.setdefault("GOOL_REMOTE_BEST_BET_STATE", str(HOME / "remote_best_bet_state.json"))
    e.setdefault("GOOL_REMOTE_BEST_BET_POLL_SECONDS", "75")
    e.setdefault("GOOL_MARKET_DB", str(HOME / "gool_market.sqlite3"))
    return e


def start(script, e, cwd=HOME):
    return subprocess.Popen([sys.executable, "-u", str(script)], cwd=str(cwd), env=e)


def stop(p):
    if p and p.poll() is None:
        try:
            p.terminate(); p.wait(timeout=6)
        except Exception:
            try: p.kill()
            except Exception: pass


def main():
    print(f"GOOL MONKEY ROOT ENTRY build={BUILD} file={Path(__file__).resolve()}", flush=True)
    disable_legacy_proguz()

    required = [COLLECTOR, LIVE, FEED, BRIDGE, BETB2B]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise SystemExit("GOOL MONKEY missing root files: " + ", ".join(missing))
    print("GOOL ROOT FILES " + " ".join(f"{p.name}={p.stat().st_size}" for p in required), flush=True)

    sync_bestbet()
    e = env()
    spec = {
        "live": (LIVE, HOME),
        "feed": (FEED, HOME),
        "store": (BRIDGE, HOME),
        "bestbet": (BESTBET_DIR / "gool_bot" / "best_bet_remote_worker.py", BESTBET_DIR / "gool_bot"),
    }
    procs = {name: start(script, e, cwd) for name, (script, cwd) in spec.items()}
    print("GOOL MONKEY ONLINE root_only=on legacy_proguz=off live_total_ou=on betb2b_1xbet=on bestbet=on", flush=True)

    stopping = False
    def sig(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, sig)
    signal.signal(signal.SIGINT, sig)

    try:
        while not stopping:
            for name, p in list(procs.items()):
                if p.poll() is not None:
                    print(f"GOOL child {name} exited rc={p.returncode}; restarting in 5s", flush=True)
                    time.sleep(5)
                    script, cwd = spec[name]
                    try:
                        procs[name] = start(script, e, cwd)
                        print(f"GOOL child {name} restarted pid={procs[name].pid}", flush=True)
                    except Exception as exc:
                        print(f"GOOL child {name} restart failed: {exc}", flush=True)
            time.sleep(3)
    finally:
        for p in procs.values(): stop(p)
        print("GOOL MONKEY stopped", flush=True)


if __name__ == "__main__":
    main()
