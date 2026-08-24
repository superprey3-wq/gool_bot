"""Low-memory LIVE odds movement / steam detector.

Keeps only a few recent points for active O/U markets. No raw history archive is
kept on the 512 MB runtime server. Recommendations are annotated with market
movement so Telegram can show whether a GOOL signal is confirmed by price action.
"""
from __future__ import annotations
import json,logging,os,time
from pathlib import Path
import live_odds,unified_bot
logger=logging.getLogger("odds_movement")
STATE=Path(os.getenv("ODDS_MOVEMENT_STATE","odds_movement_state.json"))
MAX_MARKETS=int(os.getenv("ODDS_MOVEMENT_MAX_MARKETS","700"))
MAX_POINTS=4
TTL_SECONDS=45*60
_orig_fetch=live_odds.fetch_live_odds
_orig_collect=unified_bot._collect_scope_recommendations


def _load():
    try:
        d=json.loads(STATE.read_text("utf-8"));return d if isinstance(d,dict) else {}
    except Exception:return {}

def _save(d):
    now=time.time();rows=[]
    for k,v in d.items():
        pts=v.get("p",[]) if isinstance(v,dict) else []
        if pts and now-float(pts[-1][0])<=TTL_SECONDS:rows.append((float(pts[-1][0]),k,v))
    rows.sort(reverse=True);clean={k:v for _,k,v in rows[:MAX_MARKETS]}
    tmp=STATE.with_suffix(".tmp");tmp.write_text(json.dumps(clean,separators=(",",":")),"utf-8");tmp.replace(STATE)

def _key(event_id,bid,scope,line,selection):return f"{event_id}|{bid}|{scope}|{line:g}|{selection}"

def _movement(points):
    if len(points)<2:return {"direction":"flat","drop_pct":0.0,"seconds":0,"steam":False,"strength":0}
    first=points[0];last=points[-1];old=float(first[1]);new=float(last[1]);secs=max(1,int(float(last[0])-float(first[0])))
    if old<=1 or new<=1:return {"direction":"flat","drop_pct":0.0,"seconds":secs,"steam":False,"strength":0}
    # For OVER, falling decimal odds = market moving toward more goal probability.
    drop=(old-new)/old*100.0
    implied_move=(1.0/new-1.0/old)*100.0
    strength=0
    if drop>=2.0:strength=1
    if drop>=4.0 or implied_move>=2.0:strength=2
    if drop>=7.0 or implied_move>=3.5:strength=3
    return {"direction":"toward" if drop>0.5 else "against" if drop<-0.5 else "flat","from":round(old,3),"to":round(new,3),"drop_pct":round(drop,2),"implied_move_pp":round(implied_move,2),"seconds":secs,"steam":strength>=2,"strength":strength}

def fetch_live_odds(event_id):
    rows=_orig_fetch(event_id);now=time.time();state=_load()
    for entry in rows:
        bid=entry.get("bookmakerId",0);scope=str(entry.get("bettingScope") or "FULL_TIME")
        for item in entry.get("odds") or []:
            try:line=float((item.get("handicap") or {}).get("value"));odd=float(item.get("value"));sel=str(item.get("selection") or "").upper()
            except Exception:continue
            if sel not in {"OVER","UNDER"}:continue
            k=_key(event_id,bid,scope,line,sel);obj=state.setdefault(k,{"p":[]});pts=obj.setdefault("p",[])
            if not pts or abs(float(pts[-1][1])-odd)>.0001 or now-float(pts[-1][0])>=20:
                pts.append([round(now,1),round(odd,4)]);obj["p"]=pts[-MAX_POINTS:]
            item["movement"]=_movement(obj["p"])
    _save(state);return rows

def _collect(entries,match,pressure,scope):
    rows=_orig_collect(entries,match,pressure,scope)
    for row in rows:
        line=float(row.get("line",-999));moves=[]
        for entry in entries:
            if str(entry.get("bettingScope") or "FULL_TIME")!=scope:continue
            for item in entry.get("odds") or []:
                try:il=float((item.get("handicap") or {}).get("value"))
                except Exception:continue
                if il==line and str(item.get("selection") or "").upper()=="OVER" and item.get("movement"):moves.append(item["movement"])
        toward=[m for m in moves if m.get("direction")=="toward"]
        against=[m for m in moves if m.get("direction")=="against"]
        strongest=max(moves,key=lambda m:int(m.get("strength",0)),default={})
        row["market_movement"]={"books":len(moves),"toward":len(toward),"against":len(against),"steam":any(bool(m.get("steam")) for m in moves),"strength":max([int(m.get("strength",0)) for m in moves] or [0]),"best":strongest}
    return rows

def _format_bets(recs):
    if not recs:return "Сейчас подходящего рынка тоталов нет."
    groups=[];labels={"FIRST_HALF":"🕐 <b>ДО КОНЦА 1-ГО ТАЙМА</b>","SECOND_HALF":"🕑 <b>2-Й ТАЙМ</b>","FULL_TIME":"⚽ <b>ДО КОНЦА МАТЧА</b>"}
    for scope in ("FIRST_HALF","SECOND_HALF","FULL_TIME"):
        rs=[r for r in recs if r.get("scope")==scope]
        if not rs:continue
        lines=[labels[scope]]
        for r in rs:
            books=f" · {r.get('bookmakers')} БК" if r.get("bookmakers") else "";mv=r.get("market_movement") or {}
            if mv.get("steam"):
                best=mv.get("best") or {};move=f" · 🔥 ПРОГРУЗ {best.get('from','?')}→{best.get('to','?')} ({best.get('drop_pct',0):+.1f}%)"
            elif int(mv.get("toward",0))>int(mv.get("against",0)) and mv.get("books",0):move=" · 📈 рынок движется к OVER"
            elif int(mv.get("against",0))>int(mv.get("toward",0)) and mv.get("books",0):move=" · ⚠️ рынок против OVER"
            else:move=""
            lines.append(f"ТБ {float(r['line']):g} — кэф <b>{float(r['odd']):.2f}</b> | вероятность модели <b>{r.get('confidence')}%</b>{books}{move}")
        groups.append("\n".join(lines))
    return "\n\n".join(groups)

live_odds.fetch_live_odds=fetch_live_odds
unified_bot._collect_scope_recommendations=_collect
unified_bot._format_bets=_format_bets
