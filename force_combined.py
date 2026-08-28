"""MonkeyBytes hosting entrypoint.

Keep this file tiny: the hosting panel starts force_combined.py, while the real
supervisor lives in combined_market_proguz.py.  Importing and calling main()
ensures every normal MonkeyBytes restart runs the supervisor from the checked
out browser-market-node branch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import combined_market_proguz


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(Path(__file__).resolve().parent),
            text=True,
            timeout=5,
        ).strip()
    except Exception:
        return "unknown"


def main() -> None:
    print(f"GOOL MONKEY ENTRY force_combined.py git={_git_sha()}", flush=True)
    print("GOOL MONKEY ENTRY supervisor=combined_market_proguz.py", flush=True)
    combined_market_proguz.main()


if __name__ == "__main__":
    main()
