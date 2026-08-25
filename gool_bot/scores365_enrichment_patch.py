"""365Scores candidate-only validation.

Uses the lightweight public web JSON already verified in a one-shot live probe.
No browser, no raw-history storage, tiny TTL caches. It enriches the existing
GOAL API/FotMob validation but cannot move MASTER beyond the existing +/-5 cap.
"""
from __future__ import annotations

import logging, time
from urllib.parse import urlencode

import candidate_enrichment_patch as ce

logger=logging.getLogger("scores365_enrichment")
BASE="https://webws.365scores.com/web"
LIST_TTL=180
DETAIL_TTL=150
_live_cache=(0.0,[])
_detail_cache:dict[str,tuple[float,dict]]={}


def _get(path, params):
    url=BASE+"/"+path.lstrip("/")+"?"+urlencode(params)
    return ce._http_json(url, {"User-Agent":ce.UA,"Accept":"*/*","Referer":"https://www.365scores.com/"}, timeout=9)


def _live_rows():
    global _live_cache
    now=time.time()
    if now-_live_cache[0] < LIST_TTL:return _live_cache[1]
    code,data=_get("games/",{"appTypeId":5,"langId":1,"timezoneName":"Etc/UTC","sports":1})
    rows=[]
    if code==200 and isinstance(data,dict):
        rows=[g for g in (data.get("games") or []) if isinstance(g,dict) and g.get("statusGroup")==3]
    _live_cache=(now,rows)
    return rows


def _match(m):
    best,best_s=None,0.0
    for g in _live_rows():
        h=(g.get("homeCompetitor") or {}).get("name")
        a=(g.get("awayCompetitor") or {}).get("name")
        s=ce._pair_score(m.home,m.away,h,a)
        if s>best_s:best,best_s=g,s
    return (best,best_s) if best_s>=.72 else (None,best_s)


def _detail(game_id):
    now=time.time(); c=_detail_cache.get(str(game_id))
    if c and now-c[0] < DETAIL_TTL:return c[1]
    code,data=_get("game/",{"appTypeId":5,"langId":1,"timezoneName":"Etc/UTC","gameId":game_id,"topBookmaker":14})
    game=(data.get("game") or {}) if code==200 and isinstance(data,dict) else {}
    _detail_cache[str(game_id)]=(now,game)
    return game


def _features(m):
    hit,sim=_match(m)
    if not hit:return {"matched":False,"match_score":round(sim,3)}
    gid=hit.get("id")
    if not gid:return {"matched":False,"match_score":round(sim,3)}
    game=_detail(gid)
    shots=((game.get("chartEvents") or {}).get("events") or []) if isinstance(game,dict) else []
    xg=xgot=0.0; valid_xg=valid_xgot=0
    for s in shots:
        if not isinstance(s,dict):continue
        try:
            if s.get("xg") not in (None,"","-"):
                xg+=float(s["xg"]);valid_xg+=1
        except Exception:pass
        try:
            if s.get("xgot") not in (None,"","-"):
                xgot+=float(s["xgot"]);valid_xgot+=1
        except Exception:pass
    events=game.get("events") or [] if isinstance(game,dict) else []
    reds=[e for e in events if isinstance(e,dict) and ((e.get("eventType") or {}).get("id")==3)]
    return {
        "matched":True,"game_id":str(gid),"match_score":round(sim,3),
        "shots":len(shots),"shot_xg_total":round(xg,3) if valid_xg else None,
        "shot_xgot_total":round(xgot,3) if valid_xgot else None,
        "red_cards":len(reds),"has_shotmap":bool(shots),
        "has_stats":bool(game.get("hasStats")),"has_lineups":bool(game.get("hasLineups")),
    }


_original_external=ce._external_adjustment


def _external_with_365(m):
    adj,score,ext=_original_external(m)
    s365=_features(m)
    ext["scores365"]=s365
    reasons=ext.setdefault("reasons",[])
    score=float(score)
    if s365.get("matched"):
        xg=s365.get("shot_xg_total"); xgot=s365.get("shot_xgot_total"); shots=int(s365.get("shots") or 0)
        if xg is not None:
            if float(xg)>=1.5: score+=6; reasons.append(f"365Scores shot-xG {float(xg):.2f}")
            elif float(xg)<.30 and int(m.minute or 0)>=35: score-=5; reasons.append(f"365Scores low shot-xG {float(xg):.2f}")
        if xgot is not None and float(xgot)>=1.0: score+=5; reasons.append(f"365Scores xGoT {float(xgot):.2f}")
        if shots>=10: score+=3
        if s365.get("red_cards"): reasons.append(f"365Scores red cards {s365['red_cards']}")
    score=max(0.,min(100.,score))
    adj=round(max(-5.,min(5.,(score-50.)/7.5)),1)
    return adj,score,ext


ce._external_adjustment=_external_with_365
logger.info("365Scores candidate enrichment active | public JSON | no odds dependency")
