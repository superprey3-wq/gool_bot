"""Candidate-only secondary validation from GOAL API and FotMob.

Designed for a 512 MB VPS: tiny TTL caches, no raw-history storage, and a hard
software budget for GOAL API. External data can only make a modest adjustment
and never creates a signal by itself.
"""
from __future__ import annotations

import json, logging, os, re, time, unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import live_candidate_patch

logger = logging.getLogger("candidate_enrichment")

GOAL_API_KEY = os.getenv("GOAL_API_KEY", "").strip()
GOAL_BASE = "https://api.goal-api.com/v1"
FOTMOB_BASES = ("https://www.fotmob.com/api/data", "https://www.fotmob.com/api")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/137 Safari/537.36"

# Keep a reserve below the provider's 1000/day free limit.
GOAL_DAILY_SOFT_CAP = max(50, min(900, int(os.getenv("GOAL_DAILY_SOFT_CAP", "850"))))
ENRICH_MIN_MASTER = float(os.getenv("ENRICH_MIN_MASTER", "58"))
LIVE_LIST_TTL = 300
DETAIL_TTL = 150

_goal_counter = {"day": "", "n": 0}
_goal_live_cache = (0.0, [])
_goal_stats_cache: dict[str, tuple[float, dict]] = {}
_fotmob_daily_cache: dict[str, tuple[float, list]] = {}
_fotmob_detail_cache: dict[str, tuple[float, dict]] = {}


def _norm(v: str) -> str:
    s = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|sc|ac|afc|club|deportivo|deportes|women|w|femenil|femenino)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b: return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _pair_score(h1, a1, h2, a2) -> float:
    direct = (_sim(h1, h2) + _sim(a1, a2)) / 2
    reverse = (_sim(h1, a2) + _sim(a1, h2)) / 2
    return max(direct, reverse * .88)


def _http_json(url: str, headers=None, timeout=9):
    req = Request(url, headers=headers or {"User-Agent": UA, "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def _goal_allow() -> bool:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if _goal_counter["day"] != day:
        _goal_counter.update(day=day, n=0)
    return bool(GOAL_API_KEY) and _goal_counter["n"] < GOAL_DAILY_SOFT_CAP


def _goal_get(path: str):
    if not _goal_allow(): return 0, {}
    _goal_counter["n"] += 1
    return _http_json(GOAL_BASE + path, {
        "Authorization": f"Bearer {GOAL_API_KEY}", "Accept": "application/json", "User-Agent": "GOOL/1.0"
    })


def _goal_live_rows():
    global _goal_live_cache
    now = time.time()
    if now - _goal_live_cache[0] < LIVE_LIST_TTL:
        return _goal_live_cache[1]
    code, data = _goal_get("/fixtures/live")
    rows = (data.get("data") or []) if code == 200 else []
    _goal_live_cache = (now, rows)
    return rows


def _goal_match(m):
    best, best_s = None, 0.0
    for r in _goal_live_rows():
        home = (r.get("homeTeam") or {}).get("name") if isinstance(r.get("homeTeam"), dict) else r.get("homeTeamName") or r.get("home")
        away = (r.get("awayTeam") or {}).get("name") if isinstance(r.get("awayTeam"), dict) else r.get("awayTeamName") or r.get("away")
        s = _pair_score(m.home, m.away, home, away)
        if s > best_s: best, best_s = r, s
    return (best, best_s) if best_s >= .72 else (None, best_s)


def _goal_stats(m):
    hit, match_score = _goal_match(m)
    if not hit: return {"matched": False, "match_score": round(match_score, 3)}
    fid = hit.get("id") or hit.get("fixtureId") or hit.get("matchId")
    if not fid: return {"matched": False, "match_score": round(match_score, 3)}
    c = _goal_stats_cache.get(str(fid)); now = time.time()
    if c and now - c[0] < DETAIL_TTL: data = c[1]
    else:
        code, payload = _goal_get(f"/fixtures/{fid}/statistics")
        data = payload.get("data") or {} if code == 200 else {}
        _goal_stats_cache[str(fid)] = (now, data)
    rows = (((data.get("match") or {}).get("fullTime")) or []) if isinstance(data, dict) else []
    vals = {}
    for row in rows:
        if not isinstance(row, dict): continue
        k = str(row.get("type") or "").strip().lower()
        try:
            hv = float(str(row.get("home", 0)).replace("%", "")); av = float(str(row.get("away", 0)).replace("%", ""))
        except Exception: continue
        vals[k] = (hv, av)
    return {"matched": True, "fixture_id": str(fid), "match_score": round(match_score, 3), "stats": vals}


def _fotmob_rows(date_key: str):
    now = time.time(); c = _fotmob_daily_cache.get(date_key)
    if c and now-c[0] < LIVE_LIST_TTL: return c[1]
    rows = []
    for base in FOTMOB_BASES:
        code, data = _http_json(base + "/matches?" + urlencode({"date": date_key}), timeout=10)
        if code != 200 or not isinstance(data, dict): continue
        for lg in data.get("leagues") or []:
            if isinstance(lg, dict): rows.extend(lg.get("matches") or [])
        if rows: break
    _fotmob_daily_cache[date_key] = (now, rows)
    return rows


def _fotmob_match(m):
    date_key = time.strftime("%Y%m%d", time.gmtime())
    best, best_s = None, 0.0
    for r in _fotmob_rows(date_key):
        h = (r.get("home") or {}).get("name") if isinstance(r.get("home"), dict) else r.get("homeName")
        a = (r.get("away") or {}).get("name") if isinstance(r.get("away"), dict) else r.get("awayName")
        s = _pair_score(m.home, m.away, h, a)
        if s > best_s: best, best_s = r, s
    return (best, best_s) if best_s >= .72 else (None, best_s)


def _fotmob_detail(match_id: str):
    now=time.time(); c=_fotmob_detail_cache.get(str(match_id))
    if c and now-c[0] < DETAIL_TTL: return c[1]
    out={}
    for base in FOTMOB_BASES:
        code, data=_http_json(base+"/matchDetails?"+urlencode({"matchId":match_id}), timeout=10)
        if code==200 and isinstance(data,dict): out=data; break
    _fotmob_detail_cache[str(match_id)]=(now,out); return out


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values(): yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj: yield from _walk(v)


def _fotmob_features(m):
    hit, match_score=_fotmob_match(m)
    if not hit: return {"matched":False,"match_score":round(match_score,3)}
    mid=hit.get("id") or hit.get("matchId")
    if not mid:return {"matched":False,"match_score":round(match_score,3)}
    d=_fotmob_detail(str(mid)); feats={}
    shots=[]
    try: shots=((d.get("content") or {}).get("shotmap") or {}).get("shots") or []
    except Exception: shots=[]
    if shots:
        xgs=[]; xgots=[]
        for s in shots:
            if not isinstance(s,dict):continue
            for key,target in (("expectedGoals",xgs),("xG",xgs),("expectedGoalsOnTarget",xgots),("xGOT",xgots)):
                try:
                    if s.get(key) is not None: target.append(float(s[key]))
                except Exception: pass
        if xgs: feats["shot_xg_total"]=round(sum(xgs),3)
        if xgots: feats["shot_xgot_total"]=round(sum(xgots),3)
        feats["shotmap_n"]=len(shots)
    blob=json.dumps(d,ensure_ascii=False).lower()
    feats["has_momentum"]="momentum" in blob
    feats["has_lineup"]="lineup" in blob
    feats["has_ratings"]="rating" in blob
    # Pull aggregate values by common labels without depending on one FotMob schema revision.
    for node in _walk(d):
        title=str(node.get("title") or node.get("key") or node.get("name") or "").lower()
        val=node.get("stats") if "stats" in node else node.get("value")
        if "expected goals" in title or title in {"xg","expected_goals"}:
            feats.setdefault("xg_node", val)
        elif "touches in opposition box" in title or "touches in box" in title:
            feats.setdefault("touches_box_node", val)
        elif "big chance" in title:
            feats.setdefault("big_chances_node", val)
    return {"matched":True,"match_id":str(mid),"match_score":round(match_score,3),"features":feats}


def _external_adjustment(m):
    goal=_goal_stats(m) if GOAL_API_KEY else {"matched":False,"disabled":True}
    fot=_fotmob_features(m)
    score=50.0; reasons=[]
    gs=(goal.get("stats") or {}) if goal.get("matched") else {}
    da=gs.get("dangerous attacks") or gs.get("dangerous attack")
    attacks=gs.get("attacks")
    sot=gs.get("on target") or gs.get("shots on goal")
    if da:
        total=sum(da); pace=total/max(12,int(m.minute or 1))*45
        if pace>=70: score+=12; reasons.append(f"GOAL dangerous attacks pace {pace:.0f}")
        elif pace<=25: score-=8; reasons.append(f"GOAL dangerous attacks low {pace:.0f}")
    if attacks:
        pace=sum(attacks)/max(12,int(m.minute or 1))*45
        if pace>=120: score+=6
    if sot and sum(sot)>=4: score+=6
    ff=fot.get("features") or {}
    if ff.get("shot_xg_total") is not None:
        xg=float(ff["shot_xg_total"])
        if xg>=1.5: score+=10; reasons.append(f"FotMob shot-xG {xg:.2f}")
        elif xg<.35 and int(m.minute or 0)>=35: score-=7
    if ff.get("has_momentum"): score+=2
    score=max(0.,min(100.,score))
    # Maximum +-5 master points; external data cannot manufacture a candidate.
    adj=round(max(-5.,min(5.,(score-50.)/7.5)),1)
    return adj, score, {"goal_api":goal,"fotmob":fot,"reasons":reasons,"goal_requests_today":_goal_counter["n"]}


_original_evaluate = live_candidate_patch._evaluate


def _evaluate_enriched(m,s,p,goals,market):
    result=_original_evaluate(m,s,p,goals,market)
    qualifies,route,master,sc,hz,market=result
    if float(master) < ENRICH_MIN_MASTER:
        return result
    try:
        adj, ext_score, ext=_external_adjustment(m)
        sc["EXTERNAL_VALIDATION"]=round(ext_score,1)
        market["external_validation"]=ext
        market["external_master_adjustment"]=adj
        new_master=round(max(0.,min(100.,float(master)+adj)),1)
        # External sources may veto a borderline signal but never create one from REJECT.
        if qualifies and ext_score<=30 and new_master<live_candidate_patch.ENTRY_MIN_SCORE+4:
            qualifies=False; route="EXTERNAL_CONFLICT"
        master=new_master
        logger.info("EXT_VALIDATION %s master=%s adj=%s ext=%.1f goal=%s fotmob=%s requests=%d",
                    m.event_id,master,adj,ext_score,bool(ext.get("goal_api",{}).get("matched")),
                    bool(ext.get("fotmob",{}).get("matched")),_goal_counter["n"])
    except Exception as e:
        logger.info("EXT_VALIDATION_FAIL %s %s",m.event_id,e)
    return qualifies,route,master,sc,hz,market


live_candidate_patch._evaluate=_evaluate_enriched
logger.info("Candidate enrichment patch active | GOAL cap=%d/day | min master=%.1f | FotMob candidate-only",GOAL_DAILY_SOFT_CAP,ENRICH_MIN_MASTER)
