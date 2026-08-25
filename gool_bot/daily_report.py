"""Resolve GOOL BOT signal results and send a daily Telegram report."""
from __future__ import annotations
import os,re
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from live_engine import fetch_summary
from signal_journal import all_signals,update_signal
BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","");CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","");MOSCOW=ZoneInfo("Europe/Moscow")

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

def _pct(wins,losses):
    total=wins+losses
    return round(wins*100/total) if total else 0

def _avg_pressure(rows):
    vals=[]
    for row,_,_ in rows:
        try:vals.append(float(row.get("pressure",0)))
        except (TypeError,ValueError):pass
    return round(sum(vals)/len(vals)) if vals else 0

def _split_live(rows,reason):
    subset=[x for x in rows if str(x[0].get("reason") or "signal")==reason]
    wins=sum(1 for _,r,_ in subset if r=="+");losses=sum(1 for _,r,_ in subset if r=="-")
    return len(subset),wins,losses,_pct(wins,losses)

def main():
    today=datetime.now(MOSCOW).date().isoformat();rows=[]
    for row in all_signals():
        try:created=datetime.fromtimestamp(int(row.get("created_ts",0)),MOSCOW)
        except Exception:continue
        if created.date().isoformat()!=today:continue
        kind=row.get("kind")
        if kind=="live" and str(row.get("reason") or "signal") not in {"signal","reentry"}:continue
        body=fetch_summary(str(row.get("event_id","")))
        if not body:continue
        fh,fa,hh,ha=_score_from_summary(body)
        if fh+fa==0 and row.get("score_at_signal") not in {"0:0",None}:continue
        if kind=="prematch":
            goals=_market_goals(str(row.get("scope","Матч")),fh,fa,hh,ha);result=_settle_total(str(row.get("side","ТБ")),float(row.get("line",0)),goals);update_signal(row["dedupe_key"],result=result,final_score=f"{fh}:{fa}");rows.append((row,result,f"{fh}:{fa}"))
        elif kind=="live":
            try:sh,sa=map(int,str(row.get("score_at_signal","0:0")).split(":"))
            except Exception:sh=sa=0
            next_goal=(fh+fa)>(sh+sa);primary=row.get("primary") or {};bet_result=_settle_total("ТБ",float(primary.get("line",0)),fh+fa) if primary else "—";result="+" if next_goal else "-";update_signal(row["dedupe_key"],result=result,bet_result=bet_result,final_score=f"{fh}:{fa}");rows.append((row,result,f"{fh}:{fa}"))
    live=[x for x in rows if x[0].get("kind")=="live"];pre=[x for x in rows if x[0].get("kind")=="prematch"]
    lp=sum(1 for _,r,_ in live if r=="+");lm=sum(1 for _,r,_ in live if r=="-")
    pp=sum(1 for _,r,_ in pre if r in {"+","+½"});pm=sum(1 for _,r,_ in pre if r in {"-","-½"});push=sum(1 for _,r,_ in pre if r=="ВОЗВРАТ")
    initial_n,initial_w,initial_l,initial_pct=_split_live(live,"signal");re_n,re_w,re_l,re_pct=_split_live(live,"reentry")
    won_live=[x for x in live if x[1]=="+"];lost_live=[x for x in live if x[1]=="-"]
    lines=[
        f"📊 <b>GOOL BOT — ОТЧЁТ ЗА {datetime.now(MOSCOW).strftime('%d.%m.%Y')}</b>","",
        "🔴 <b>LIVE: КАЧЕСТВО СИГНАЛОВ</b>",
        f"Реальных входов: <b>{len(live)}</b> · ✅ {lp} / ❌ {lm}",
        f"Точность next-goal: <b>{_pct(lp,lm)}%</b>",
        f"Первичные: <b>{initial_n}</b> · ✅ {initial_w} / ❌ {initial_l} · <b>{initial_pct}%</b>",
        f"Повторные: <b>{re_n}</b> · ✅ {re_w} / ❌ {re_l} · <b>{re_pct}%</b>",
        f"Среднее давление: успешные <b>{_avg_pressure(won_live)}/100</b> · неуспешные <b>{_avg_pressure(lost_live)}/100</b>",
        "ℹ️ Гол-подтверждения и служебные обновления не считаются отдельными входами.","",
        "🔥 <b>ПРЕДМАТЧЕВЫЕ ПРОГРУЗЫ</b>",
        f"Рассчитано: <b>{len(pre)}</b> · ✅ {pp} / ❌ {pm} / ↩️ {push}",
        f"Проход без возвратов: <b>{_pct(pp,pm)}%</b>",
    ]
    if live:
        lines += ["","<b>Последние LIVE-входы:</b>"]
        for row,res,score in live[-12:]:
            label="RE" if str(row.get("reason") or "signal")=="reentry" else "IN";primary=row.get("primary") or {};market=f" · ТБ {primary.get('line'):g} @ {primary.get('odd'):.2f}" if isinstance(primary.get("line"),(int,float)) and isinstance(primary.get("odd"),(int,float)) else "";lines.append(f"{'✅' if res=='+' else '❌'} {label} · {row.get('home')} — {row.get('away')} | {row.get('minute')}' {row.get('score_at_signal')} → {score} · P {float(row.get('pressure',0)):.0f}{market}")
    if pre:
        lines += ["","<b>Прогрузы:</b>"]
        for row,res,score in pre[-16:]:lines.append(f"{'✅' if res in {'+','+½'} else '➖' if res=='ВОЗВРАТ' else '❌'} {row.get('home')} — {row.get('away')} | {row.get('scope')} {row.get('side')} {row.get('line')} → {score} ({res})")
    lines += ["","<i>Главная метрика LIVE — результат реального входа, а не количество сообщений по матчу.</i>"];_send("\n".join(lines));return 0

if __name__=="__main__":raise SystemExit(main())
