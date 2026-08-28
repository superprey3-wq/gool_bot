"""Make BEST BET delivery transactional from the user's point of view.

The old path wrote a pending journal row before Telegram send. If sendPhoto failed,
that invisible pending row permanently blocked retries for the event. Send first,
then persist; keep an in-memory cooldown if delivery succeeded but journaling failed.
"""
from __future__ import annotations
import logging,time
import best_bet_engine as bbe

log=logging.getLogger("best_bet_delivery_reliability")


def evaluate_match(m):
    eid=str(m.event_id);now=time.time()
    if bbe._pending(eid) or (eid in bbe._ACTIVE and now-bbe._ACTIVE[eid]<bbe.COOLDOWN):
        return False
    try:
        body=bbe.fetch_stats(eid)
        stats=bbe.parse_stats(body) if body else {}
        p=bbe.calculate_goal_pressure(m,stats,None)
        entries=bbe.unified_bot._fetch_event_odds(eid)
        recs,_=bbe.lc._market(entries,m,p)
    except Exception as exc:
        log.info("BEST_BET input unavailable %s %s",eid,exc);return False

    bbe.market_movement.annotate(recs,event_id=eid,score=f"{m.home_score}:{m.away_score}",minute=m.minute)
    for r in recs:
        r["gool_model_prob"]=bbe.model_probability(r,m,stats)
        opp=next((x for x in recs if x is not r and x.get("odd") and bbe._same_pair(r,x)),None)
        if opp:
            r["market_fair_prob"]=bbe.two_way_fair(r.get("odd"),opp.get("odd"))[0]
            r["pair_confirmed"]=bool(r["market_fair_prob"])

    ranked=[]
    for r in recs:
        if r.get("scope")!="FULL_TIME" or r.get("odd") is None:
            continue
        x=bbe._rank(r,m,p)
        if x:
            ranked.append(x)
    ranked.sort(key=lambda x:x["score"],reverse=True)
    if not ranked:
        return False
    best=ranked[0]
    if (best["score"]<bbe.MIN_SCORE or best["edge"]<bbe.MIN_EDGE or
        best["status"] in {"CONFLICT","DISAGREE","REVERSAL"} or best["suspicious"]):
        return False

    try:
        png=bbe.render_entry(m,best,ranked[1:4])
        sent=bbe._send(png,f"🏆 GOOL BEST BET • {best['name']} @ {best['odd']:.2f}")
    except Exception:
        log.exception("BEST_BET entry card failed event=%s",eid);sent=False
    if not sent:
        log.error("BEST_BET_DELIVERY_FAILED event=%s name=%s score=%.1f edge=%.1f; journal not locked",eid,best["name"],best["score"],best["edge"])
        return False

    bbe._ACTIVE[eid]=now
    key=bbe._record(m,best)
    if not key:
        # Telegram already received the card; prevent duplicates even if journal I/O failed.
        log.error("BEST_BET_JOURNAL_FAILED_AFTER_SEND event=%s name=%s",eid,best["name"])
    log.info("BEST_BET_SENT %s %s score=%.1f edge=%.1f journal=%s",eid,best["name"],best["score"],best["edge"],bool(key))
    return True

bbe.evaluate_match=evaluate_match
log.info("BEST BET delivery reliability active | send-before-journal")
