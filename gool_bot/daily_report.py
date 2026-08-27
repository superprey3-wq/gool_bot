"""Resolve GOOL BOT signal results and send a daily Telegram report."""
from __future__ import annotations
import os,re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from live_engine import fetch_summary
from market_settlement import settle_primary
from signal_journal import all_signals,update_signal
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","");CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","");MOSCOW=ZoneInfo("Europe/Moscow")
PREMATCH_MIN_STRENGTH=float(os.getenv("PREMATCH_MIN_STRENGTH","75"))

def _send(text):
    if not BOT_TOKEN or not CHAT_ID:return False
    try:return requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True},timeout=20).ok
    except requests.RequestException:return False

def _score_from_summary(body):
    final_h=final_a=ht_h=ht_a=0
    for chunk in body.split("~III"):
        mm=re.search(r"(?:IB|IBX)(?:÷|¬)(\d{1,3})",chunk);hm=re.search(r"INX(?:÷|¬)(\d+)",chunk);am=re.search(r"IOX(?:÷|¬)(\d+)",chunk)
        if not hm and not am:continue
        h=int(hm.group(1)) if hm else final_h;a=int(am.group(1)) if am else final_a;final_h=max(final_h,h);final_a=max(final_a,a)
        if mm and int(mm.group(1))<=45:ht_h=max(ht_h,h);ht_a=max(ht_a,a)
    return final_h,final_a,ht_h,ht_a

def _settle_total(side,line,goals):
    diff=goals-line
    if side=="ТБ":
        if diff>0.25:return "+"
        if diff==0.25:return "+½"
        if diff==0:return "ВОЗВРАТ"
        if diff==-0.25:return "-½"
        return "-"
    if diff<-0.25:return "+"
    if diff==-0.25:return "+½"
    if diff==0:return "ВОЗВРАТ"
    if diff==0.25:return "-½"
    return "-"

def _market_goals(scope,fh,fa,hh,ha):
    if scope=="1-й тайм":return hh+ha
    if scope=="2-й тайм":return (fh+fa)-(hh+ha)
    return fh+fa

def _first_number(row,keys):
    for key in keys:
        if key not in row or row.get(key) is None:continue
        try:return float(row.get(key))
        except (TypeError,ValueError):continue
    return None

def _prematch_visible(row):
    block=_first_number(row,("block_count","blocks","blocking_count","block_level","block_score","block"))
    if block is not None and block<1:return False
    strength=_first_number(row,("strength","signal_strength","confidence","rating","score","master"))
    if strength is not None and strength<PREMATCH_MIN_STRENGTH:return False
    return True

def main():
    today=datetime.now(MOSCOW).date().isoformat();rows=[]
    for row in all_signals():
        try:created=datetime.fromtimestamp(int(row.get("created_ts",0)),MOSCOW)
        except Exception:continue
        if created.date().isoformat()!=today:continue
        kind=row.get("kind")
        if kind=="live" and str(row.get("reason") or "signal") not in {"signal","reentry"}:continue
        if kind=="prematch" and not _prematch_visible(row):continue
        body=fetch_summary(str(row.get("event_id","")))
        if not body:continue
        fh,fa,hh,ha=_score_from_summary(body);final_score=f"{fh}:{fa}"
        if fh+fa==0 and row.get("score_at_signal") not in {"0:0",None}:continue
        if kind=="prematch":
            goals=_market_goals(str(row.get("scope","Матч")),fh,fa,hh,ha);result=_settle_total(str(row.get("side","ТБ")),float(row.get("line",0)),goals);update_signal(row["dedupe_key"],result=result,final_score=final_score);rows.append((row,result,final_score))
        elif kind=="live":
            try:sh,sa=map(int,str(row.get("score_at_signal","0:0")).split(":"))
            except Exception:sh=sa=0
            next_goal=(fh+fa)>(sh+sa);result="+" if next_goal else "-";settlement=settle_primary(row.get("primary"),final_score) or {};fields={"result":result,"signal_result":"win" if next_goal else "loss","final_score":final_score}
            if settlement:
                fields.update({"bet_result":settlement.get("result"),"bet_pnl_units":settlement.get("pnl_units"),"bet_settled_market":settlement.get("settled_market"),"bet_settled_line":settlement.get("settled_line"),"bet_settled_odd":settlement.get("settled_odd")})
            update_signal(row["dedupe_key"],**{k:v for k,v in fields.items() if v is not None});rows.append((row,result,final_score))
    live=[x for x in rows if x[0].get("kind")=="live"];pre=[x for x in rows if x[0].get("kind")=="prematch"]
    lp=sum(1 for _,r,_ in live if r=="+");lm=sum(1 for _,r,_ in live if r=="-");pp=sum(1 for _,r,_ in pre if r in {"+","+½"});pm=sum(1 for _,r,_ in pre if r in {"-","-½"})
    initial=sum(1 for row,_,_ in live if str(row.get("reason") or "signal")=="signal");reentries=sum(1 for row,_,_ in live if str(row.get("reason") or "signal")=="reentry")
    lines=[f"📊 <b>ИТОГИ GOOL BOT — {datetime.now(MOSCOW).strftime('%d.%m.%Y')}</b>","","🔴 <b>LIVE</b>",f"Всего реальных входов: <b>{len(live)}</b>",f"↳ Первичных: <b>{initial}</b> · повторных: <b>{reentries}</b>",f"✅ Следующий гол был: <b>{lp}</b>",f"❌ Следующего гола не было: <b>{lm}</b>","ℹ️ Результат конкретной LIVE-ставки хранится отдельно в bet_result/bet_pnl_units.","",f"🔥 <b>ПРЕДМАТЧЕВЫЕ ПРОГРУЗЫ</b>",f"✅ Зашли: <b>{pp}</b>",f"❌ Не зашли: <b>{pm}</b>",f"Всего рассчитано: {len(pre)}"]
    if live:
        lines += ["","<b>LIVE-входы:</b>"]
        for row,res,score in live[-12:]:
            label="ПОВТОРНЫЙ ВХОД" if str(row.get("reason") or "signal")=="reentry" else "ВХОД";lines.append(f"{'✅' if res=='+' else '❌'} {label} · {row.get('home')} — {row.get('away')} | {row.get('minute')}' {row.get('score_at_signal')} → {score}")
    if pre:
        lines += ["","<b>Прогрузы:</b>"]
        for row,res,score in pre[-16:]:lines.append(f"{'✅' if res in {'+','+½'} else '➖' if res=='ВОЗВРАТ' else '❌'} {row.get('home')} — {row.get('away')} | {row.get('scope')} {row.get('side')} {row.get('line')} → {score} ({res})")
    lines += ["",f"<i>Прогрузы: блокировка 0 скрывается; при наличии рейтинга показываются только {PREMATCH_MIN_STRENGTH:.0f}+.</i>","<i>LIVE: факт следующего гола и результат выбранного рынка считаются раздельно.</i>"];_send("\n".join(lines));return 0

if __name__=="__main__":raise SystemExit(main())
