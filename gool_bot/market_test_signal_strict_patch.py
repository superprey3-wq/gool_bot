"""Strict quality gate + paired O/U prices for owner TOP-load total alerts.

Patches the real market_test_signal generator before Telegram delivery.
Rules are fail-closed and intentionally selective. For opposite-direction moves
we also search the market-node snapshot for the other side of the exact same
full-match total line so Telegram can show a real current price instead of a
blind direction whenever that price exists upstream.
"""
from __future__ import annotations
import logging, os, re
import market_test_signal as mts
import market_node_bridge as mnb

log=logging.getLogger("market_test_signal_strict")

MIN_BLOCKS=int(os.getenv("TOPLOAD_MIN_BLOCKS","4"))
MIN_REOPENS=int(os.getenv("TOPLOAD_MIN_REOPEN","3"))
MIN_MOVE_PP=float(os.getenv("TOPLOAD_MIN_MOVE_PP","10.0"))
MAX_MOVE_AGE=int(os.getenv("TOPLOAD_MAX_MOVE_AGE","420"))
MAX_LIVE_MINUTE=int(os.getenv("TOPLOAD_MAX_LIVE_MINUTE","75"))
LATE_FROM=int(os.getenv("TOPLOAD_LATE_FROM","60"))
LATE_MIN_BLOCKS=int(os.getenv("TOPLOAD_LATE_MIN_BLOCKS","5"))
LATE_MIN_REOPENS=int(os.getenv("TOPLOAD_LATE_MIN_REOPEN","4"))
LATE_MIN_MOVE_PP=float(os.getenv("TOPLOAD_LATE_MIN_MOVE_PP","12.0"))
LATE_MAX_MOVE_AGE=int(os.getenv("TOPLOAD_LATE_MAX_MOVE_AGE","300"))

_orig_eligible_time=mts._eligible_time
_orig_message=mts._message
_orig_recommendation=mts._recommendation


def _meta(s):
    x=mts._enrich(s)
    try: minute=int(x.get("minute") or x.get("match_minute") or 0)
    except Exception: minute=0
    try: blocks=int(x.get("suspends",0) or 0)
    except Exception: blocks=0
    try: reopens=int(x.get("reopens",0) or 0)
    except Exception: reopens=0
    try: move=abs(float(x.get("delta_pp",0) or 0))
    except Exception: move=0.0
    try: age=max(0,int(x.get("elapsed",0) or 0))
    except Exception: age=10**9
    status=str(x.get("status") or x.get("state") or "").casefold()
    live=("live" in status or str(x.get("is_live") or "").casefold() in ("1","true","yes") or minute>0)
    return x,minute,blocks,reopens,move,age,live


def _strict_sharp(s):
    x,minute,blocks,reopens,move,age,live=_meta(s)
    if blocks<MIN_BLOCKS:
        log.info("TOPLOAD_REJECT reason=blocks blocks=%d min=%d",blocks,MIN_BLOCKS);return False
    if reopens<MIN_REOPENS:
        log.info("TOPLOAD_REJECT reason=reopens reopens=%d min=%d",reopens,MIN_REOPENS);return False
    if move<MIN_MOVE_PP:
        log.info("TOPLOAD_REJECT reason=move move=%.2f min=%.2f",move,MIN_MOVE_PP);return False
    if age<=0 or age>MAX_MOVE_AGE:
        log.info("TOPLOAD_REJECT reason=stale age=%d max=%d",age,MAX_MOVE_AGE);return False
    if live:
        if minute>MAX_LIVE_MINUTE:
            log.info("TOPLOAD_REJECT reason=late minute=%d max=%d",minute,MAX_LIVE_MINUTE);return False
        if minute>=LATE_FROM and (blocks<LATE_MIN_BLOCKS or reopens<LATE_MIN_REOPENS or move<LATE_MIN_MOVE_PP or age>LATE_MAX_MOVE_AGE):
            log.info("TOPLOAD_REJECT reason=late_quality minute=%d blocks=%d reopen=%d move=%.2f age=%d",minute,blocks,reopens,move,age);return False
    return True


def _strict_eligible_time(s):
    if not _orig_eligible_time(s):return False
    x,minute,blocks,reopens,move,age,live=_meta(s)
    if live and minute>MAX_LIVE_MINUTE:return False
    return True


def _f(v):
    try:
        x=float(v)
        return x if x>1.0 else None
    except Exception:return None


def _line(row):
    for k in ("last_line","line","handicap","total","points"):
        try:
            if row.get(k) is not None:return float(row.get(k))
        except Exception:pass
    raw=" ".join(str(row.get(k) or "") for k in ("market","selection","name","label"))
    m=re.search(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)",raw)
    try:return float(m.group(1)) if m else None
    except Exception:return None


def _side(row):
    try:
        ti=int(row.get("type_id"))
        if ti==9:return "over"
        if ti==10:return "under"
    except Exception:pass
    raw=" ".join(str(row.get(k) or "") for k in ("selection","side","outcome","market","name","label")).casefold()
    if re.search(r"\b(over|o)\b",raw) or "тб" in raw:return "over"
    if re.search(r"\b(under|u)\b",raw) or "тм" in raw:return "under"
    return ""


def _odd(row):
    for k in ("last_odds","current_odds","current","odds","price","best_odds","last_price"):
        v=_f(row.get(k))
        if v:return v
    return None


def _book(row):
    return str(row.get("bookmaker_id") or row.get("bookmaker") or row.get("book") or row.get("source") or "")


def _walk(obj,depth=0):
    if depth>5:return
    if isinstance(obj,dict):
        yield obj
        for k,v in obj.items():
            if k in ("points","history","timeline"):continue
            if isinstance(v,(dict,list,tuple)):
                yield from _walk(v,depth+1)
    elif isinstance(obj,(list,tuple)):
        for v in obj:yield from _walk(v,depth+1)


def _remote_row(s):
    try:
        _,row,mode,similarity=mnb._lookup_remote(s.get("home") or "",s.get("away") or "")
        if row:return row
    except Exception as exc:
        log.debug("TOPLOAD_PAIR_REMOTE_LOOKUP_FAIL %s",exc)
    return {}


def _opposite_price(s):
    target_line=_line(s)
    if target_line is None:return None,""
    shown_side="over" if mts._is_over(s) else "under"
    want="under" if shown_side=="over" else "over"
    shown_book=_book(s)
    containers=[s,_remote_row(s)]
    candidates=[]
    seen=set()
    for container in containers:
        for row in _walk(container):
            if id(row) in seen:continue
            seen.add(id(row))
            if _side(row)!=want:continue
            ln=_line(row)
            if ln is None or abs(ln-target_line)>0.011:continue
            odd=_odd(row)
            if not odd:continue
            book=_book(row)
            same_book=1 if shown_book and book and shown_book==book else 0
            candidates.append((same_book,odd,book,row))
    if not candidates:
        log.info("TOPLOAD_PAIR_MISSING home=%s away=%s line=%s want=%s",s.get("home"),s.get("away"),target_line,want)
        return None,""
    # Prefer the exact same bookmaker. If unavailable, use the best current
    # opposite price visible in the event snapshot and mark its source.
    same=[c for c in candidates if c[0]]
    pool=same or candidates
    best=max(pool,key=lambda x:x[1])
    log.info("TOPLOAD_PAIR_FOUND line=%s want=%s odd=%.3f book=%s same_book=%s",target_line,want,best[1],best[2] or "?",bool(best[0]))
    return best[1],best[2]


def _paired_recommendation(s,d):
    if d>0:
        # The moved side itself has a real current price already. Add the pair
        # below when available so the operator sees the complete market.
        base=_orig_recommendation(s,d)
        opp,book=_opposite_price(s)
        if opp:
            return base+f"\n↔️ <b>Обратный кэф:</b> <b>{mts._opposite_name(s)} @ {opp:.2f}</b>"+(f" · {book}" if book else "")
        return base+"\n<i>⚠️ Обратный кэф той же линии в snapshot не найден.</i>"
    opp,book=_opposite_price(s)
    if opp:
        shown=_f(s.get("last_odds"))
        extra=""
        if shown:
            overround=(1.0/shown)+(1.0/opp)
            if overround>0:
                fair=(1.0/opp)/overround*100.0
                extra=f"\n📐 No-vig вероятность направления: <b>{fair:.1f}%</b>"
        src=f" · {book}" if book else ""
        return f"🎯 <b>Рыночное направление:</b> <b>{mts._opposite_name(s)} @ {opp:.2f}</b>{src}\n✅ <b>Обратный кэф получен</b> для той же линии.{extra}"
    return f"🧭 <b>Рыночное направление:</b> <b>{mts._opposite_name(s)}</b>\n<i>⚠️ VALUE НЕ ПОДТВЕРЖДЁН: обратный кэф той же линии реально отсутствует в текущем snapshot.</i>"


def _strict_message(s):
    text=_orig_message(s)
    text=text.replace("<i>Только тоталы матча ТБ/ТМ · кэф от 1.35 · LIVE или старт ≤2ч · топ-5 · один сигнал на матч.</i>","<i>Фильтр PRO: ≥4 блокировок · ≥3 reopen · движение ≥10 п.п. · окно ≤420с · LIVE ≤75' · с 60' только ≥5/4, ≥12 п.п., ≤300с.</i>")
    return text

mts._sharp=_strict_sharp
mts._eligible_time=_strict_eligible_time
mts._recommendation=_paired_recommendation
mts._message=_strict_message
log.info("MARKET_TEST_STRICT_GATE enabled blocks=%d reopen=%d move=%.1f age=%d max_live=%d late_from=%d paired_ou=on",MIN_BLOCKS,MIN_REOPENS,MIN_MOVE_PP,MAX_MOVE_AGE,MAX_LIVE_MINUTE,LATE_FROM)
