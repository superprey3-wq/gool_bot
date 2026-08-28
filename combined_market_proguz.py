"""MonkeyBytes combined runtime: market collector + GOOL PROGRUZ + schedule preload."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path(os.getenv("GOOL_HOME", "/home/container"))
PROGUZ_DIR = HOME / "proguz_runtime"
REPO = "https://github.com/superprey3-wq/gool_bot.git"
PROGUZ_BRANCH = "live-only-quant-foundation"
COLLECTOR = HOME / "browser_market_node.py"
SCHEDULE_PATH = HOME / "market_schedule.json"
SCHEDULE_REFRESH_SECONDS = max(120, int(os.getenv("GOOL_SCHEDULE_REFRESH_SECONDS", "300")))
FLASH_BASE = "https://local-global.flashscore.ninja/2/x/feed/"
FLASH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "*/*",
    "Referer": "https://www.flashscore.com/",
    "Origin": "https://www.flashscore.com",
    "x-fsign": "SW9D1eZo",
    "Cache-Control": "no-cache",
}


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
    env.setdefault("GOOL_MARKET_STATE", str(HOME / "market_node_state.json"))
    env.setdefault("GOOL_MARKET_HISTORY", str(HOME / "market_node_history_v6.json"))
    env.setdefault("GOOL_MARKET_SCHEDULE", str(SCHEDULE_PATH))
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


def _http_get(url):
    try:
        from curl_cffi import requests as req
        r = req.get(url, headers=FLASH_HEADERS, timeout=15, allow_redirects=True, impersonate="chrome")
    except Exception:
        import requests as req
        r = req.get(url, headers=FLASH_HEADERS, timeout=15, allow_redirects=True)
    r.raise_for_status()
    return r.text or ""


def _decode(text):
    rows = []
    for item in (text or "").split("~"):
        row = {}
        for part in item.split("¬"):
            sep = "÷" if "÷" in part else "·" if "·" in part else None
            if not sep:
                continue
            k, v = part.split(sep, 1)
            if k in row:
                n = 2
                while f"{k}_{n}" in row:
                    n += 1
                k = f"{k}_{n}"
            row[k] = v
        if row:
            rows.append(row)
    return rows


def _events(rows, day):
    out = []
    for r in rows:
        eid = r.get("AA")
        if not eid:
            continue
        out.append({
            "event_id": str(eid),
            "day": day,
            "home": r.get("AE") or r.get("CX") or "",
            "away": r.get("AF") or r.get("CX_2") or "",
            "home_score": r.get("AG"),
            "away_score": r.get("AH"),
            "status": r.get("AC") or "",
            "start_ts": r.get("AD") or r.get("AB"),
            "tournament": r.get("ZA") or r.get("ZB") or "",
            "country": r.get("ZY") or r.get("ZC") or "",
            "source": "flashscore",
        })
    return out


def _refresh_schedule_once():
    all_events = []
    counts = {}
    for day, offset in (("today", 0), ("tomorrow", 1)):
        url = f"{FLASH_BASE}f_1_{offset}_3_en_1"
        body = _http_get(url)
        evs = _events(_decode(body), day)
        counts[day] = len(evs)
        all_events.extend(evs)
    unique = {}
    for e in all_events:
        unique[e["event_id"]] = e
    payload = {"ts": time.time(), "source": "flashscore", "counts": counts, "total": len(unique), "events": list(unique.values())}
    tmp = SCHEDULE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SCHEDULE_PATH)
    print(f"FLASH_SCHEDULE_PRELOAD today={counts.get('today',0)} tomorrow={counts.get('tomorrow',0)} total={len(unique)}", flush=True)
    return len(unique)


def schedule_loop(stop_event):
    while not stop_event.is_set():
        try:
            _refresh_schedule_once()
        except Exception as exc:
            print(f"FLASH_SCHEDULE_ERROR {type(exc).__name__}: {exc}", flush=True)
        stop_event.wait(SCHEDULE_REFRESH_SECONDS)


def main():
    print("GOOL COMBINED MARKET+PROGRUZ+SCHEDULE starting", flush=True)
    sync_proguz()
    install_requirements()
    env = child_env()
    collector = start_collector(env)
    proguz = start_proguz(env)
    stop_event = threading.Event()
    schedule = threading.Thread(target=schedule_loop, args=(stop_event,), name="flash-schedule", daemon=True)
    schedule.start()
    print(f"GOOL COMBINED ONLINE collector_pid={collector.pid} proguz_pid={proguz.pid} schedule=today+tomorrow", flush=True)

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
        stop_event.set()
        stop_child(proguz)
        stop_child(collector)
        print("GOOL COMBINED stopped", flush=True)


if __name__ == "__main__":
    main()
