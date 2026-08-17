"""Read-only 1xBet/Melbet LiveFeed probe for GOOL shadow testing.

Never changes CORE decisions. It probes modern /service-api/LiveFeed endpoints,
matches GOOL/Flashscore live games and reports market payloads. Important:
1xBet compact field P is the market parameter/handicap, not automatically the
full-match total. We only label a market as FT total when its compact type is
confirmed by the paired T=9/T=10 structure; everything else stays diagnostic.
"""
from __future__ import annotations
import logging, os, re, unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any
import requests
logger=logging.getLogger("xbet_live_odds")
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137 Safari/537.36"
DEFAULT_ROOTS=("https://1xbet.com/service-api/LiveFeed","https://1xbet.fi/service-api/LiveFeed","https://melbet.com/service-api/LiveFeed","https://1xbet.com/LiveFeed","https://1xbet.fi/LiveFeed")
ROOTS=tuple(x.strip().rstrip("/") for x in os.getenv("XBET_LIVE_ROOTS",",".join(DEFAULT_ROOTS)).split(",") if x.strip())
HEADERS={"User-Agent":UA,"Accept":"application/json,text/plain,*/*","Accept-Language":"en-US,en;q=0.9","Referer":"https://1xbet.com/","Origin":"https://1xbet.com"}
TIMEOUT=float(os.getenv("XBET_TIMEOUT","10"))

def _get(method,param_variants):
    attempts=[];last_error=None
    for root in ROOTS:
        url=f"{root}/{method}";headers=dict(HEADERS)
        if "melbet" in root: headers.update({"Referer":"https://melbet.com/","Origin":"https://melbet.com"})
        for params in param_variants:
            try:
                r=requests.get(url,params=params,headers=headers,timeout=TIMEOUT,allow_redirects=True);attempts.append(f"{root} -> HTTP {r.status_code}")
                if r.status_code!=200:last_error=f"{root}: HTTP {r.status_code}";continue
                try:data=r.json()
                except ValueError:last_error=f"{root}: non-JSON";attempts[-1]+=" non-JSON";continue
                if isinstance(data,dict) and "Value" in data:attempts[-1]+=" JSON/Value";return data,root,None,attempts
                last_error=f"{root}: JSON without Value";attempts[-1]+=" JSON-no-Value"
            except requests.RequestException as exc:last_error=f"{root}: {type(exc).__name__}: {exc}";attempts.append(last_error)
    return {},"",last_error,attempts

def _live_param_variants():
    return [{"sports":1,"count":1000,"lng":"en","mode":4,"country":1,"getEmpty":"true"},{"sports":1,"count":1000,"lng":"en","mode":4,"country":137,"gr":285,"virtualSports":"true","noFilterBlockEvent":"true","getEmpty":"true"}]

def fetch_live_football():
    data,root,err,attempts=_get("Get1x2_VZip",_live_param_variants());v=data.get("Value") if isinstance(data,dict) else None
    return (v if isinstance(v,list) else []),root,err,attempts

def fetch_game(event_id,preferred_root=None):
    global ROOTS
    old=ROOTS
    try:
        if preferred_root and preferred_root in ROOTS:ROOTS=(preferred_root,)+tuple(r for r in ROOTS if r!=preferred_root)
        data,root,err,attempts=_get("GetGameZip",[{"id":event_id,"lng":"en","cfview":0,"isSubGames":"true","GroupEvents":"true","allEventsGroupSubGames":"true","countevents":250,"grMode":2}])
    finally:ROOTS=old
    v=data.get("Value") if isinstance(data,dict) else None
    return (v if isinstance(v,dict) else {}),root,err,attempts

def _norm(text):
    s=unicodedata.normalize("NFKD",str(text or "")).encode("ascii","ignore").decode().lower();s=s.replace("women"," w ").replace("ladies"," w ");s=re.sub(r"\b(fc|fk|cf|sc|afc|club|football|futbol|soccer)\b"," ",s);s=re.sub(r"[^a-z0-9]+"," ",s);return " ".join(s.split())
def _sim(a,b):
    a,b=_norm(a),_norm(b)
    if not a or not b:return 0.0
    if a==b:return 1.0
    ta,tb=set(a.split()),set(b.split());return max(len(ta&tb)/max(1,len(ta|tb)),SequenceMatcher(None,a,b).ratio())
def match_event(home,away,events):
    best=None;bs=0.;revbest=False
    for e in events:
        h,a=e.get("O1") or e.get("O1E"),e.get("O2") or e.get("O2E");normal=(_sim(home,h)+_sim(away,a))/2;rev=(_sim(home,a)+_sim(away,h))/2;score,isrev=(rev,True) if rev>normal else (normal,False)
        if score>bs:best,bs,revbest=e,score,isrev
    return (None,bs,revbest) if bs<.62 else (best,bs,revbest)

def _collect(obj,out,path=""):
    if isinstance(obj,dict):
        if "C" in obj and ("T" in obj or "P" in obj):
            try:odd=float(obj.get("C"))
            except:odd=0
            if odd>1:
                row={k:obj.get(k) for k in ("T","C","P","G","CE","CV","N") if k in obj};row["path"]=path;out.append(row)
        for k,v in obj.items():_collect(v,out,f"{path}/{k}"[-120:])
    elif isinstance(obj,list):
        for i,v in enumerate(obj):_collect(v,out,f"{path}[{i}]"[-120:])

def market_diagnostics(game,current_goals):
    nodes=[];_collect(game,nodes)
    # Compact 1xBet football convention observed in our live payload:
    # T=9/T=10 is the paired full-time Total Over/Under selection. P is the
    # TOTAL LINE itself (0.5, 1.5, ...), so for score 0:0 target is P=0.5.
    ft_over=[n for n in nodes if n.get("T")==9];ft_under=[n for n in nodes if n.get("T")==10]
    by_line=defaultdict(dict)
    for n in ft_over+ft_under:
        try:p=float(n.get("P"))
        except:continue
        by_line[p]["over" if n.get("T")==9 else "under"]=n
    target=current_goals+0.5;pair=by_line.get(target,{})
    # Also expose all T9/T10 lines so we can verify behavior after goals.
    lines=[]
    for p in sorted(by_line):
        d=by_line[p];lines.append({"line":p,"over":(d.get("over") or {}).get("C"),"under":(d.get("under") or {}).get("C")})
    groups=defaultdict(int)
    for n in nodes:groups[str(n.get("G","-"))]+=1
    return {"bet_nodes":len(nodes),"target_line":target,"ft_total_pair":pair,"ft_total_lines":lines[:20],"group_counts":dict(sorted(groups.items(),key=lambda kv:-kv[1])[:12]),"sample_nodes":nodes[:8]}

def probe_matches(matches):
    events,root,err,attempts=fetch_live_football();result={"root":root,"error":err,"attempts":attempts,"xbet_live_count":len(events),"matches":[]}
    if not events:return result
    for m in matches:
        home,away=str(getattr(m,"home","")),str(getattr(m,"away",""));sh=int(getattr(m,"home_score",0) or 0);sa=int(getattr(m,"away_score",0) or 0);row={"home":home,"away":away,"minute":int(getattr(m,"minute",0) or 0),"score":f"{sh}:{sa}"}
        e,sim,rev=match_event(home,away,events);row["similarity"]=round(sim,3)
        if not e:row["found"]=False;result["matches"].append(row);continue
        row.update({"found":True,"xbet_id":e.get("I"),"xbet_home":e.get("O1") or e.get("O1E"),"xbet_away":e.get("O2") or e.get("O2E"),"xbet_league":e.get("L") or e.get("LE"),"reversed":rev})
        game,gr,ge,ga=fetch_game(e.get("I"),root);row.update({"game_root":gr,"game_error":ge,"game_attempts":ga})
        if game:row["markets"]=market_diagnostics(game,sh+sa)
        result["matches"].append(row)
    return result

def format_probe(result):
    lines=["🧪 <b>1xBET LIVE TOTAL PROBE</b>"]
    if result.get("root"):lines.append(f"✅ Feed: <code>{result['root']}</code>")
    lines.append(f"LIVE football: <b>{result.get('xbet_live_count',0)}</b>")
    for r in result.get("matches") or []:
        lines.append("");lines.append(f"⚽ <b>{r['home']} — {r['away']}</b> | {r['minute']}' {r['score']}")
        if not r.get("found"):lines.append(f"❌ не найдено · match {round(float(r.get('similarity',0))*100)}%");continue
        lines.append(f"✅ 1xBet: {r.get('xbet_home')} — {r.get('xbet_away')} · {round(float(r.get('similarity',0))*100)}%")
        m=r.get("markets") or {};lines.append(f"ID <code>{r.get('xbet_id')}</code> · selections <b>{m.get('bet_nodes',0)}</b>")
        pair=m.get("ft_total_pair") or {};ov=pair.get("over");un=pair.get("under")
        if ov or un:
            lines.append(f"🎯 <b>FT TOTAL {m.get('target_line')}</b> · OVER <b>{(ov or {}).get('C','—')}</b> · UNDER <b>{(un or {}).get('C','—')}</b>")
            lines.append("⚠️ shadow: пока не влияет на CORE")
        else:
            lines.append(f"ℹ️ FT Total {m.get('target_line','—')} сейчас не найден/закрыт")
            avail=m.get("ft_total_lines") or []
            if avail:lines.append("Доступные T9/T10: <code>"+"; ".join(f"{x['line']} O={x['over']} U={x['under']}" for x in avail[:8])+"</code>")
    return "\n".join(lines)
