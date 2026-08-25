"""Daily GOOL 2.0 Telegram report.

The product now has three independent LIVE systems:
1) CORE: best concrete market (TOTAL/BTTS/team total) or analytics-only when no fresh odds.
2) FIRST_HALF_GOAL: goal in the first half, signalled in the 15-25 minute window.
3) SECOND_HALF_OVER15: Over 1.5 goals in the second half, decided at half-time.

Prematch lines are intentionally excluded. Fresh LIVE odds are optional metadata,
not a prerequisite for counting model accuracy.
"""
from __future__ import annotations
import os,re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","");CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","");MOSCOW=ZoneInfo("Europe/Moscow")

def _send(text):
    if not BOT_TOKEN or not CHAT_ID:return False
    try:return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=20).ok
    except requests.RequestException:return False

def _score_from_summary(body):
    final_h=final_a=ht_h=ht_a=0
    for chunk in str(body or "").split("~III"):
        mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})",chunk);hm=re.search(r"INX(?:÷|¬)(\d+)",chunk);am=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
        if not hm and not am:continue
        h=int(hm.group(1)) if hm else final_h;a=int(am.group(1)) if am else final_a;final_h=max(final_h,h);final_a=max(final_a,a)
        if mm and int(mm.group(1))<=45:ht_h=max(ht_h,h);ht_a=max(ht_a,a)
    return final_h,final_a,ht_h,ht_a

def main():
    # report_now is the single source of truth for the three GOOL 2.0 systems.
    # Import here to avoid the circular dependency: report_now imports the score parser above.
    from report_now import build_report_text
    text=build_report_text().replace("GOOL 2.0 — ОТЧЁТ НА СЕЙЧАС",f"GOOL 2.0 — ИТОГИ ДНЯ {datetime.now(MOSCOW).strftime('%d.%m.%Y')}")
    _send(text);return 0

if __name__=="__main__":raise SystemExit(main())
