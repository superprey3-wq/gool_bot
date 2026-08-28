"""One-shot Playwright Chromium installer for the MonkeyBytes browser node."""
from __future__ import annotations

import shutil
import subprocess
import sys


def mb(n: int) -> float:
    return n / 1048576.0


def main() -> int:
    usage = shutil.disk_usage("/home/container")
    free = mb(usage.free)
    print(f"GOOL_CHROMIUM_INSTALL disk_free={free:.1f}MB", flush=True)
    if free < 500:
        print("GOOL_CHROMIUM_INSTALL SKIP: need at least 500MB free", flush=True)
        return 2
    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    print("GOOL_CHROMIUM_INSTALL running: playwright install chromium", flush=True)
    rc = subprocess.call(cmd)
    usage = shutil.disk_usage("/home/container")
    print(f"GOOL_CHROMIUM_INSTALL done rc={rc} disk_free={mb(usage.free):.1f}MB", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
