"""Reliable local PNG result card for confirmed CORE bets.

Goal-result rendering must not depend on remote logos or enrichment calls. This patch
keeps entry cards untouched and replaces only the confirmed-result delivery path.
"""
from __future__ import annotations
from io import BytesIO
import logging
import requests
from PIL import Image,ImageDraw,ImageFont
import telegram_image_signal_patch as tip

log=logging.getLogger("core_goal_result_card")
_orig_send_photo_all=tip._send_photo_all
W,H=1080,900
BG=(5,10,18);PANEL=(13,22,36);PANEL2=(19,31,49);TEXT=(247,249,252);MUTED=(151,166,188);GREEN=(82,220,118);GOLD=(255,184,48);CYAN=(61,178,255);LINE=(45,63,88)

def _font(size,bold=False):
 paths=[
  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
  "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
 ]
 for path in paths:
  try:return ImageFont.truetype(path,size)
  except OSError:pass
 return ImageFont.load_default()

def _fit(draw,text,width,start=38,bold=True):
 text=str(text or "")
 for size in range(start,15,-2):
  f=_font(size,bold)
  if draw.textbbox((0,0),text,font=f)[2]<=width:return f
 return _font(16,bold)

def _center(draw,text,y,font,fill):
 box=draw.textbbox((0,0),str(text),font=font)
 draw.text(((W-(box[2]-box[0]))/2,y),str(text),font=font,fill=fill)

def _render(match,recs,master):
 primary=(recs or [None])[0]
 label=tip._primary_label(primary)
 odd=None
 if isinstance(primary,dict):
  try:odd=float(primary.get("odd")) if primary.get("odd") is not None else None
  except Exception:odd=None
 entry=tip._pending_row(getattr(match,"event_id","") or "") or {}
 entry_score=str(entry.get("score_at_signal") or "—")
 try:entry_min=int(entry.get("minute",0) or 0)
 except Exception:entry_min=0
 minute=int(getattr(match,"minute",0) or 0)
 score=f"{int(getattr(match,'home_score',0) or 0)} : {int(getattr(match,'away_score',0) or 0)}"
 title=f"{getattr(match,'home','?')} — {getattr(match,'away','?')}"
 img=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(img)
 d.rounded_rectangle((24,20,1056,112),24,fill=PANEL,outline=GREEN,width=3)
 d.text((52,34),"GOOL CORE",font=_font(36,True),fill=GREEN);d.text((52,78),"VERIFIED RESULT CARD",font=_font(15,True),fill=TEXT)
 d.rounded_rectangle((850,38,1026,92),16,outline=GREEN,width=2);d.text((884,53),"WIN",font=_font(20,True),fill=GREEN)
 _center(d,title,160,_fit(d,title,900,34,True),TEXT)
 _center(d,f"{minute}'  •  {score}",212,_font(30,True),CYAN)
 d.rounded_rectangle((55,285,1025,500),28,fill=PANEL2,outline=GREEN,width=3)
 _center(d,"✓ СТАВКА ЗАШЛА",318,_font(38,True),GREEN)
 _center(d,label,378,_fit(d,label,860,44,True),TEXT)
 if odd and odd>1:_center(d,f"КЭФ {odd:.2f}",438,_font(31,True),GOLD)
 d.rounded_rectangle((55,545,1025,705),22,fill=PANEL,outline=LINE,width=2)
 d.text((85,570),"ВХОД",font=_font(16,True),fill=MUTED)
 d.text((85,608),f"{entry_min}' • счёт {entry_score}",font=_font(26,True),fill=TEXT)
 d.text((585,570),"ПОДТВЕРЖДЕНИЕ",font=_font(16,True),fill=MUTED)
 d.text((585,608),f"{minute}' • счёт {score}",font=_font(26,True),fill=GREEN)
 rating=float(master or entry.get("candidate_score") or entry.get("pressure") or 0)
 d.text((85,665),f"GOOL на входе: {rating:.0f}/100",font=_font(18,True),fill=MUTED)
 _center(d,"Результат относится к конкретной выбранной ставке",770,_font(20,True),TEXT)
 _center(d,"GOOL AI • CORE RESULT",830,_font(18,True),MUTED)
 out=BytesIO();img.save(out,"PNG",optimize=True);return out.getvalue(),label

def _fallback(match,recs):
 primary=(recs or [None])[0];label=tip._primary_label(primary)
 return (f"✅ <b>GOOL AI • СТАВКА ЗАШЛА</b>\n\n"
         f"⚽ <b>{getattr(match,'home','?')} — {getattr(match,'away','?')}</b>\n"
         f"⏱ {int(getattr(match,'minute',0) or 0)}' • <b>{int(getattr(match,'home_score',0) or 0)}:{int(getattr(match,'away_score',0) or 0)}</b>\n"
         f"🎯 <b>{label}</b>")

def _send_photo_all(match,pressure,recs,kind,master=None):
 if kind!="goal":return _orig_send_photo_all(match,pressure,recs,kind,master)
 token=tip.unified_bot.BOT_TOKEN;recipients=tip.get_subscribers()
 if not token or not recipients:return False
 try:png,label=_render(match,recs,master)
 except Exception as exc:
  log.exception("CORE_GOAL_CARD_RENDER_FAILED: %s",exc);png=None;label=tip._primary_label((recs or [None])[0])
 delivered=0
 for chat_id in recipients:
  ok=False
  if png:
   try:
    r=requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",data={"chat_id":str(chat_id),"caption":f"✅ GOOL AI • СТАВКА ЗАШЛА • {label}"},files={"photo":("gool-core-result.png",png,"image/png")},timeout=25)
    ok=bool(r.ok)
    if not ok:log.warning("CORE_GOAL_CARD_UPLOAD_FAILED chat=%s status=%s body=%s",chat_id,getattr(r,"status_code",None),str(getattr(r,"text",''))[:160])
   except requests.RequestException as exc:log.warning("CORE_GOAL_CARD_UPLOAD_FAILED chat=%s: %s",chat_id,exc)
  if not ok:ok=tip._send_text_to_chat(token,chat_id,_fallback(match,recs))
  delivered+=int(bool(ok))
 log.info("CORE_GOAL_CARD delivered=%d/%d event=%s",delivered,len(recipients),getattr(match,"event_id",""))
 return delivered>0

tip._send_photo_all=_send_photo_all
log.info("CORE_GOAL_RESULT_CARD enabled local_png=1 remote_assets=0")
