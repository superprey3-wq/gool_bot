"""Owner-only /xbetcheck command for read-only 1xBet LiveFeed testing."""
from __future__ import annotations
import logging,re
import telegram_subscribers as tg
logger=logging.getLogger("xbet_probe_patch")
_original_handle_message=tg._handle_message

def _parse_score_value(v):
    if isinstance(v,str):
        m=re.search(r"(\d+)\s*[:\-]\s*(\d+)",v)
        if m:return int(m.group(1)),int(m.group(2))
    if isinstance(v,dict):
        # 1xBet SC usually stores final/current score in SC.FS. Missing S2 means 0.
        if isinstance(v.get("FS"),dict):
            fs=v["FS"]
            if "S1" in fs or "S2" in fs:
                try:return int(fs.get("S1",0) or 0),int(fs.get("S2",0) or 0)
                except:pass
        if "S1" in v or "S2" in v:
            try:return int(v.get("S1",0) or 0),int(v.get("S2",0) or 0)
            except:pass
    return None

def _fresh_score(event,game,flash_home,flash_away):
    for source,obj in (("game",game),("event",event)):
        if isinstance(obj,dict):
            for k in ("SC","FS","Score","score"):
                if k in obj:
                    parsed=_parse_score_value(obj.get(k))
                    if parsed:return parsed[0],parsed[1],f"1xBet {source}.{k}"
    return flash_home,flash_away,"Flashscore"

def _build_probe(matches):
    from xbet_live_odds import fetch_live_football,match_event,fetch_game
    from xbet_market_decoder import decode,format_markets
    events,root,err,attempts=fetch_live_football();lines=["🧪 <b>1xBET GOOL ODDS SHADOW</b>"]
    if root:lines.append(f"✅ Feed: <code>{root}</code>")
    lines.append(f"LIVE football: <b>{len(events)}</b>")
    if not events:lines.append(f"⚠️ {err or 'feed пуст'}");return "\n".join(lines),len(events)
    for m in matches:
        home=str(getattr(m,"home",""));away=str(getattr(m,"away",""));fsh=int(getattr(m,"home_score",0) or 0);fsa=int(getattr(m,"away_score",0) or 0);minute=int(getattr(m,"minute",0) or 0)
        event,sim,rev=match_event(home,away,events)
        if not event:
            lines+=['',f"⚽ <b>{home} — {away}</b> | {minute}' {fsh}:{fsa}",f"❌ не найдено · match {round(float(sim)*100)}%"]
            continue
        game,game_root,game_err,game_attempts=fetch_game(event.get('I'),root)
        if not game:
            lines+=['',f"⚽ <b>{home} — {away}</b> | {minute}' {fsh}:{fsa}",f"✅ 1xBet: {event.get('O1') or event.get('O1E')} — {event.get('O2') or event.get('O2E')} · {round(float(sim)*100)}%",f"⚠️ GetGameZip: {game_err or 'пустой ответ'}"]
            continue
        sh,sa,score_source=_fresh_score(event,game,fsh,fsa)
        lines+=['',f"⚽ <b>{home} — {away}</b> | {minute}' {sh}:{sa}"]
        if (sh,sa)!=(fsh,fsa):lines.append(f"🔄 Flashscore {fsh}:{fsa} → 1xBet <b>{sh}:{sa}</b>")
        lines.append(f"✅ 1xBet: {event.get('O1') or event.get('O1E')} — {event.get('O2') or event.get('O2E')} · {round(float(sim)*100)}%")
        decoded=decode(game,sh+sa,minute);lines.append(f"selections: <b>{decoded.get('count',0)}</b>");lines.extend(format_markets(decoded))
    return "\n".join(lines),len(events)
def _handle_message(message:dict):
    text=str(message.get('text') or '').strip();command=text.split(maxsplit=1)[0].lower() if text else ''
    if '@' in command:command=command.split('@',1)[0]
    if command!='/xbetcheck':return _original_handle_message(message)
    chat_id=(message.get('chat') or {}).get('id')
    if chat_id is None:return
    if str(chat_id)!=tg._owner_chat_id():tg._send_reply(chat_id,'⛔ 1xBet probe доступен только владельцу.');return
    tg._send_reply(chat_id,'🧪 Проверяю 1xBet: счёт / гол в 1-м тайме / тоталы матча / обе забьют…')
    try:
        from live_engine import _feed
        from feed_live_discovery import parse_master_live
        body=_feed('f_1_0_0_en_1');matches=parse_master_live(body) if body else []
        text_out,xbet_count=_build_probe(matches)
        while text_out:
            part=text_out[:3900];cut=part.rfind('\n\n')
            if len(text_out)>3900 and cut>1000:part=text_out[:cut]
            tg._send_reply(chat_id,part);text_out=text_out[len(part):].lstrip()
        logger.info('1xBet GOOL odds probe: flash=%d xbet=%d',len(matches),xbet_count)
    except Exception as exc:
        logger.exception('1xBet owner probe failed: %s',exc);tg._send_reply(chat_id,f'⚠️ 1xBet probe упал: <code>{type(exc).__name__}: {exc}</code>')
tg._handle_message=_handle_message
logger.info('1xBet /xbetcheck GOOL odds shadow enabled')
