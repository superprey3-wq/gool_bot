"""Resolve GOOL BOT signal results and send a daily Telegram report."""
from __future__ import annotations

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

from live_engine import fetch_summary
from signal_journal import all_signals, update_signal

BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","")
MOSCOW=ZoneInfo("Europe/Moscow")


def _send(text:str)->bool:
    if not BOT_TOKEN or not CHAT_ID:return False
    try:
        return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=20).ok
    except requests.RequestException:return False


def _score_from_summary(body:str)->tuple[int,int,int,int]:
    """Return final home/away and first-half home/away from cumulative summary events."""
    final_h=final_a=ht_h=ht_a=0
    for chunk in body.split("~III"):
        mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})",chunk)
        hm=re.search(r"INX(?:÷|¬)(\d+)",chunk); am=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
        if not hm and not am:continue
        h=int(hm.group(1)) if hm else final_h; a=int(am.group(1)) if am else final_a
        final_h=max(final_h,h); final_a=max(final_a,a)
        if mm and int(mm.group(1))<=45:
            ht_h=max(ht_h,h); ht_a=max(ht_a,a)
    return final_h,final_a,ht_h,ht_a


def _settle_total(side:str,line:float,goals:int)->str:
    # Asian quarter-lines are treated conservatively as win/loss/push/half-win/half-loss labels.
    diff=goals-line
    if side=="ТБ":
        if diff>0.25:return "+"
        if diff==0.25:return "+½"
        if diff==0:return "ВОЗВРАТ"
        if diff==-0.25:return "-½"
        return "-"
    else:
        if diff<-0.25:return "+"
        if diff==-0.25:return "+½"
        if diff==0:return "ВОЗВРАТ"
        if diff==0.25:return "-½"
        return "-"


def _market_goals(scope:str,fh:int,fa:int,hh:int,ha:int)->int:
    if scope=="1-й тайм":return hh+ha
    if scope=="2-й тайм":return (fh+fa)-(hh+ha)
    return fh+fa


def main()->int:
    today=datetime.now(MOSCOW).date().isoformat(); rows=[]
    for row in all_signals():
        created=datetime.fromtimestamp(int(row.get("created_ts",0)),MOSCOW)
        if created.date().isoformat()!=today:continue
        body=fetch_summary(str(row.get("event_id","")))
        if not body:continue
        fh,fa,hh,ha=_score_from_summary(body)
        if fh+fa==0 and row.get("score_at_signal") not in {"0:0",None}:continue
        kind=row.get("kind")
        if kind=="prematch":
            goals=_market_goals(str(row.get("scope","Матч")),fh,fa,hh,ha)
            result=_settle_total(str(row.get("side","ТБ")),float(row.get("line",0)),goals)
            update_signal(row["dedupe_key"],result=result,final_score=f"{fh}:{fa}")
            rows.append((row,result,f"{fh}:{fa}"))
        elif kind=="live":
            try:sh,sa=map(int,str(row.get("score_at_signal","0:0")).split(":"))
            except Exception:sh=sa=0
            next_goal=(fh+fa)>(sh+sa)
            primary=row.get("primary") or {}
            if primary:
                bet_result=_settle_total("ТБ",float(primary.get("line",0)),fh+fa)
            else:bet_result="—"
            result="+" if next_goal else "-"
            update_signal(row["dedupe_key"],result=result,bet_result=bet_result,final_score=f"{fh}:{fa}")
            rows.append((row,result,f"{fh}:{fa}"))
    live=[x for x in rows if x[0].get("kind")=="live"]; pre=[x for x in rows if x[0].get("kind")=="prematch"]
    lp=sum(1 for _,r,_ in live if r=="+"); lm=sum(1 for _,r,_ in live if r=="-")
    pp=sum(1 for _,r,_ in pre if r in {"+","+½"}); pm=sum(1 for _,r,_ in pre if r in {"-","-½"})
    lines=[f"📊 <b>ИТОГИ GOOL BOT — {datetime.now(MOSCOW).strftime('%d.%m.%Y')}</b>","",f"🔴 <b>LIVE</b>",f"✅ Сигналы +: <b>{lp}</b>",f"❌ Сигналы -: <b>{lm}</b>",f"Всего рассчитано: {len(live)}","",f"🔥 <b>ПРЕДМАТЧЕВЫЕ ПРОГРУЗЫ</b>",f"✅ Зашли: <b>{pp}</b>",f"❌ Не зашли: <b>{pm}</b>",f"Всего рассчитано: {len(pre)}"]
    if live:
        lines += ["","<b>LIVE по матчам:</b>"]
        for row,res,score in live[-12:]:lines.append(f"{ '✅' if res=='+' else '❌'} {row.get('home')} — {row.get('away')} | {row.get('minute')}' {row.get('score_at_signal')} → {score}")
    if pre:
        lines += ["","<b>Прогрузы:</b>"]
        for row,res,score in pre[-16:]:lines.append(f"{ '✅' if res in {'+','+½'} else '➖' if res=='ВОЗВРАТ' else '❌'} {row.get('home')} — {row.get('away')} | {row.get('scope')} {row.get('side')} {row.get('line')} → {score} ({res})")
    lines += ["","<i>Статистика накапливается для последующей калибровки модели и оценки реального прироста от прогрузов.</i>"]
    _send("\n".join(lines)); return 0

if __name__=="__main__":raise SystemExit(main())
