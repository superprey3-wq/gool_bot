"""Render compact PNG cards for Telegram LIVE football signals.

The card is deliberately best-effort: missing logos/fonts/network never block the
normal text signal. Team logos are read from the same Flashscore master feed
(OA/OB fields) and downloaded from Flashscore's static image CDN.
"""
from __future__ import annotations
from io import BytesIO
import logging,re
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card")
W,H=1080,720; BG=(15,20,30); PANEL=(24,31,44); TEXT=(245,247,250); MUTED=(158,169,187); ACCENT=(255,181,46); DANGER=(239,78,78); GREEN=(76,194,129)
def _font(size:int,bold:bool=False):
    paths=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for path in paths:
        try:return ImageFont.truetype(path,size)
        except OSError:pass
    return ImageFont.load_default()
def _fields(record):
    out={}
    for token in record.split("¬"):
        if "÷" in token:
            k,v=token.split("÷",1); out.setdefault(k,v)
    return out
def _logo_names(event_id):
    body=_feed("f_1_0_0_en_1"); needle=f"AA÷{event_id}¬"
    if not body or needle not in body:return "",""
    for chunk in body.split("~"):
        if needle in chunk:
            f=_fields(chunk); return f.get("OA",""),f.get("OB","")
    return "",""
def _download_logo(filename,size=150):
    if not filename:return None
    for url in [f"https://static.flashscore.com/res/image/data/{filename}",f"https://static.flashscore.com/res/image/data/{filename}?v=1"]:
        try:
            r=requests.get(url,timeout=6,headers={"User-Agent":"Mozilla/5.0"})
            if r.ok and r.content:
                img=Image.open(BytesIO(r.content)).convert("RGBA"); img.thumbnail((size,size),Image.Resampling.LANCZOS); canvas=Image.new("RGBA",(size,size),(0,0,0,0)); canvas.alpha_composite(img,((size-img.width)//2,(size-img.height)//2)); return canvas
        except Exception:continue
    return None
def _initials(name):
    words=re.findall(r"[A-Za-zА-Яа-я0-9]+",name)
    return "".join(w[0] for w in words[:2]).upper() if words else "?"
def _paste_badge(base,draw,x,y,logo,name):
    r=82; draw.ellipse((x-r,y-r,x+r,y+r),fill=(36,45,61),outline=(72,84,104),width=3)
    if logo:base.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
    else:
        t=_initials(name); f=_font(46,True); box=draw.textbbox((0,0),t,font=f); draw.text((x-(box[2]-box[0])/2,y-(box[3]-box[1])/2-4),t,font=f,fill=TEXT)
def _fit_text(draw,text,max_width,start_size=42,bold=True):
    for size in range(start_size,23,-2):
        f=_font(size,bold)
        if draw.textbbox((0,0),text,font=f)[2]<=max_width:return f
    return _font(24,bold)
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None)->bytes:
    recs=recs or []; img=Image.new("RGBA",(W,H),BG+(255,)); draw=ImageDraw.Draw(img)
    draw.rounded_rectangle((38,30,W-38,105),24,fill=PANEL); draw.text((70,50),"GOOL BOT  •  LIVE",font=_font(31,True),fill=ACCENT)
    risk="ВЫСОКИЙ РИСК" if match.minute>=80 else "LIVE АНАЛИЗ"; risk_color=DANGER if match.minute>=80 else GREEN; rb=draw.textbbox((0,0),risk,font=_font(25,True)); draw.text((W-70-(rb[2]-rb[0]),54),risk,font=_font(25,True),fill=risk_color)
    hn,an=_logo_names(match.event_id); hl=_download_logo(hn); al=_download_logo(an); _paste_badge(img,draw,185,245,hl,match.home); _paste_badge(img,draw,W-185,245,al,match.away)
    score=f"{match.home_score} : {match.away_score}"; sf=_font(78,True); sb=draw.textbbox((0,0),score,font=sf); draw.text(((W-(sb[2]-sb[0]))/2,190),score,font=sf,fill=TEXT)
    minute="ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'"; mf=_font(30,True); mb=draw.textbbox((0,0),minute,font=mf); draw.text(((W-(mb[2]-mb[0]))/2,285),minute,font=mf,fill=ACCENT)
    hf=_fit_text(draw,match.home,360,36); af=_fit_text(draw,match.away,360,36); hb=draw.textbbox((0,0),match.home,font=hf); ab=draw.textbbox((0,0),match.away,font=af); draw.text((185-(hb[2]-hb[0])/2,345),match.home,font=hf,fill=TEXT); draw.text((W-185-(ab[2]-ab[0])/2,345),match.away,font=af,fill=TEXT)
    league=getattr(match,"league","") or "Турнир уточняется"; lf=_fit_text(draw,league,W-150,26,False); lb=draw.textbbox((0,0),league,font=lf); draw.text(((W-(lb[2]-lb[0]))/2,402),league,font=lf,fill=MUTED)
    draw.rounded_rectangle((55,460,510,650),28,fill=PANEL); draw.rounded_rectangle((570,460,1025,650),28,fill=PANEL); draw.text((85,488),"ДАВЛЕНИЕ НА ГОЛ",font=_font(24,True),fill=MUTED); p=int(round(float(getattr(pressure,"score",0)))); draw.text((85,530),f"{p}/100",font=_font(55,True),fill=ACCENT if p<90 else DANGER); draw.rounded_rectangle((85,603,470,621),9,fill=(48,58,74)); draw.rounded_rectangle((85,603,85+int(385*max(0,min(100,p))/100),621),9,fill=ACCENT if p<90 else DANGER)
    best=next((r for r in recs if r.get("full_match_best")),None) or next((r for r in recs if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)
    if best:
        draw.text((600,488),"ЛУЧШАЯ СТАВКА НА МАТЧ",font=_font(22,True),fill=MUTED); draw.text((600,530),f"ТБ {float(best['line']):g}  @  {float(best['odd']):.2f}",font=_font(43,True),fill=TEXT); source=str(best.get("source") or "LIVE рынок"); conf=int(best.get("confidence",0)); detail=f"Модель: {conf}%  •  {source}" if conf else source; df=_fit_text(draw,detail,390,27,True); draw.text((600,592),detail,font=df,fill=GREEN)
    else:
        draw.text((600,488),"ЛУЧШАЯ СТАВКА НА МАТЧ",font=_font(22,True),fill=MUTED); draw.text((600,538),"LIVE-кэф\nнедоступен",font=_font(34,True),fill=TEXT,spacing=8)
    out=BytesIO(); img.convert("RGB").save(out,"PNG",optimize=True); return out.getvalue()
