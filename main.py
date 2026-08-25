"""Repository entrypoint: run the single GOOL LIVE production runner."""
from __future__ import annotations
import runpy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BOT_DIR=ROOT/"gool_bot"
if str(BOT_DIR) not in sys.path:sys.path.insert(0,str(BOT_DIR))
if __name__=="__main__":runpy.run_path(str(BOT_DIR/"main.py"),run_name="__main__")
