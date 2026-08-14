"""Small persistent index of the latest Telegram entry card for each match."""
from __future__ import annotations
import json,os,time
from pathlib import Path
ARCHIVE_FILE=Path(os.getenv("SIGNAL_CARD_ARCHIVE_FILE",str(Path(__file__).with_name("signal_card_archive.json"))))

def _load():
    if not ARCHIVE_FILE.exists():return {}
    try:
        data=json.loads(ARCHIVE_FILE.read_text(encoding="utf-8"));return data if isinstance(data,dict) else {}
    except Exception:return {}

def _save(data):
    try:
        ARCHIVE_FILE.parent.mkdir(parents=True,exist_ok=True)
        ARCHIVE_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:pass

def save_entry_card(event_id,file_id,caption="🔥 GOOL AI • МОЖНО ЗАХОДИТЬ"):
    eid=str(event_id or "").strip();fid=str(file_id or "").strip()
    if not eid or not fid:return
    data=_load();data[eid]={"file_id":fid,"caption":caption,"saved_ts":int(time.time())};_save(data)

def get_entry_card(event_id):
    return _load().get(str(event_id or "")) or None
