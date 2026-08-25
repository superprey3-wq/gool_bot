"""Compatibility entrypoint for hosting panels that require app.py.

Delegates to the real GOOL production entrypoint in main.py.
"""
from __future__ import annotations
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    runpy.run_path(str(ROOT / "main.py"), run_name="__main__")
