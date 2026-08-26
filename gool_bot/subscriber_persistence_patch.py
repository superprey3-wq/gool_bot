"""Keep Telegram subscribers on the same persistent storage as the GOOL journal when possible."""
from __future__ import annotations
import json,logging,os,re
from pathlib import Path
import telegram_subscribers as tg
import telegram_image_signal_patch as tip

log=logging.getLogger("subscriber_persistence_patch")


def _persistent_file():
 explicit=os.getenv("TELEGRAM_SUBSCRIBERS_FILE","").strip()
 if explicit:return Path(explicit)
 runtime=os.getenv("RUNTIME_DATA_DIR","").strip()
 if runtime:return Path(runtime)/"telegram_subscribers.json"
 journal=os.getenv("SIGNAL_JOURNAL_FILE","").strip()
 if journal:
  p=Path(journal)
  if p.is_absolute():return p.parent/"telegram_subscribers.json"
 data=Path("/data")
 if data.exists() and os.access(str(data),os.W_OK):return data/"telegram_subscribers.json"
 db=os.getenv("DATABASE_PATH","").strip()
 if db:
  p=Path(db)
  if p.is_absolute():return p.parent/"telegram_subscribers.json"
 return tg.SUBSCRIBERS_FILE

STORE=_persistent_file()
LEGACY={tg.SUBSCRIBERS_FILE,tg.LEGACY_SUBSCRIBERS_FILE,Path.cwd()/"telegram_subscribers.json"}

def _read(path):
 try:
  if not path.exists():return set()
  raw=json.loads(path.read_text(encoding="utf-8"))
  return {str(x).strip() for x in raw if str(x).strip()} if isinstance(raw,list) else set()
 except Exception as exc:
  log.warning("SUBSCRIBERS_READ_FAIL path=%s err=%s",path,exc);return set()

def _extras():
 raw=os.getenv("TELEGRAM_EXTRA_CHAT_IDS","")
 return {x for x in re.split(r"[\s,;]+",raw.strip()) if x}

def _saved():
 ids=_read(STORE)
 for p in LEGACY:
  ids|=_read(p)
 return ids

def _write(ids):
 vals=sorted({str(x).strip() for x in ids if str(x).strip()})
 try:
  STORE.parent.mkdir(parents=True,exist_ok=True)
  STORE.write_text(json.dumps(vals,ensure_ascii=False,indent=2),encoding="utf-8")
  return True
 except Exception as exc:
  log.error("SUBSCRIBERS_WRITE_FAIL path=%s err=%s",STORE,exc);return False

def get_subscribers():
 ids=_saved()|_extras();owner=tg._owner_chat_id()
 if owner:ids.add(str(owner))
 return sorted(ids)

def subscribe(chat_id):
 cid=str(chat_id).strip()
 if not cid:return False
 ids=_saved();before=len(ids);ids.add(cid);_write(ids);return len(ids)!=before

def unsubscribe(chat_id):
 cid=str(chat_id).strip();ids=_saved();had=cid in ids;ids.discard(cid);_write(ids);return had

# Migrate anything still present on this deployment into persistent storage.
_write(_saved())

tg.SUBSCRIBERS_FILE=STORE
tg.get_subscribers=get_subscribers
tg.subscribe=subscribe
tg.unsubscribe=unsubscribe
# telegram_image_signal_patch imported get_subscribers by value earlier, so patch it too.
tip.get_subscribers=get_subscribers
log.info("SUBSCRIBERS_PERSIST path=%s recipients=%d",STORE,len(get_subscribers()))
