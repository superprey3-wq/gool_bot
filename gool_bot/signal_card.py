"""Premium Telegram PNG cards for GOOL actionable LIVE signals."""
from __future__ import annotations
from io import BytesIO
import logging,re
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card")
W,H=1080,1080; BG=(10,15,24); PANEL=(22,29,42); TEXT=(246,248,252); MUTED=(153,165,184); GOLD=(255,187,56); GREEN=(65,205,132); RED=(240,82,82); LINE=(49,61,80)

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
            k,v=token.split("÷",1);out.setdefault(k,v)
    return out

def _logo_names(event_id):
    body=_feed("f_1_0_0_en_1");needle=f"AA÷{event_id}¬"
    if not body or needle not in body:return "",""
    for chunk in body.split("~"):
        if needle in chunk:
            f=_fields(chunk);return f.get("OA",""),f.get("OB","")
    return "",""

def _download_logo(filename,size=135):
    if not filename:return None
    try:
        r=requests.get(f"https://static.flashscore.com/res/image/data/{filename}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.ok:
            im=Image.open(BytesIO(r.content)).convert("RGBA");im.thumbnail((size,size),Image.Resampling.LANCZOS);return im
    except Exception:pass
    return None

def _initials(name):
    w=re.findall(r"[A-Za-zА-Яа-я0-9]+",name);return "".join(x[0] for x in w[:2]).upper() if w else "?"

def _badge(img,draw,x,y,logo,name):
    r=72;draw.ellipse((x-r,y-r,x+r,y+r),fill=(31,40,56),outline=LINE,width=3)
    if logo:img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
    else:
        t=_initials(name);f=_font(40,True);b=draw.textbbox((0,0),t,font=f);draw.text((x-(b[2]-b[0])/2,y-(b[3]-b[1])/2-3),t,font=f,fill=TEXT)

def _fit(draw,text,width,start=38,bold=True):
    for s in range(start,21,-2):
        f=_font(s,bold)
        if draw.textbbox((0,0),text,font=f)[2]<=width:return f
    return _font(22,bold)

def _center(draw,text,y,font,fill):
    b=draw.textbbox((0,0),text,font=font);draw.text(((W-(b[2]-b[0]))/2,y),text,font=font,fill=fill)

def _best(recs):
    recs=recs or []
    return next((r for r in recs if r.get("best_bet")),None) or next((r for r in recs if r.get("full_match_best")),None) or next((r for r in recs if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)

def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind:str="entry",master:float|None=None,xg:dict|None=None)->bytes:
    win=kind=="goal";accent=GREEN if win else GOLD
    img=Image.new("RGBA",(W,H),BG+(255,));draw=ImageDraw.Draw(img)
    # header
    draw.rounded_rectangle((38,34,W-38,128),28,fill=PANEL,outline=LINE,width=2)
    draw.text((72,60),"GOOL AI",font=_font(34,True),fill=TEXT)
    tag="SIGNAL WON" if win else "LIVE SIGNAL"
    tb=draw.textbbox((0,0),tag,font=_font(28,True));draw.text((W-72-(tb[2]-tb[0]),64),tag,font=_font(28,True),fill=accent)
    title="СИГНАЛ ЗАШЁЛ — ГОЛ!" if win else "МОЖНО ЗАХОДИТЬ"
    _center(draw,title,165,_font(48,True),accent)
    # match block
    hn,an=_logo_names(getattr(match,"event_id",""));hl=_download_logo(hn);al=_download_logo(an)
    _badge(img,draw,190,335,hl,match.home);_badge(img,draw,W-190,335,al,match.away)
    score=f"{match.home_score} : {match.away_score}";_center(draw,score,278,_font(82,True),TEXT)
    minute="ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'";_center(draw,minute,380,_font(30,True),accent)
    hf=_fit(draw,match.home,350);af=_fit(draw,match.away,350);hb=draw.textbbox((0,0),match.home,font=hf);ab=draw.textbbox((0,0),match.away,font=af)
    draw.text((190-(hb[2]-hb[0])/2,430),match.home,font=hf,fill=TEXT);draw.text((W-190-(ab[2]-ab[0])/2,430),match.away,font=af,fill=TEXT)
    league=getattr(match,"league","") or "LIVE FOOTBALL";lf=_fit(draw,league,850,25,False);_center(draw,league,490,lf,MUTED)
    # metrics
    draw.rounded_rectangle((50,550,1030,875),30,fill=PANEL,outline=LINE,width=2)
    p=int(round(float(master if master is not None else getattr(pressure,"score",0) or 0)))
    draw.text((85,585),"РЕЙТИНГ СИГНАЛА",font=_font(23,True),fill=MUTED);draw.text((85,622),f"{p}/100",font=_font(58,True),fill=accent)
    draw.rounded_rectangle((85,700,465,718),9,fill=LINE);draw.rounded_rectangle((85,700,85+int(380*max(0,min(100,p))/100),718),9,fill=accent)
    best=_best(recs)
    draw.text((570,585),"LIVE РЫНОК",font=_font(23,True),fill=MUTED)
    if best:
        draw.text((570,627),f"ТБ {float(best['line']):g}  •  {float(best['odd']):.2f}",font=_font(43,True),fill=TEXT)
        src=str(best.get("source") or "LIVE");draw.text((570,690),src,font=_font(24,True),fill=GREEN)
    else:draw.text((570,637),"КЭФ НЕ НАЙДЕН",font=_font(32,True),fill=MUTED)
    if xg and not win:
        lam=float(xg.get("lambda",0) or 0);gp=float(xg.get("goal_probability",0) or 0);sources=int(xg.get("sources",0) or 0)
        draw.line((85,758,995,758),fill=LINE,width=2);draw.text((85,790),"GOOL XG CONSENSUS",font=_font(22,True),fill=MUTED)
        draw.text((85,825),f"{gp:.0f}%",font=_font(38,True),fill=GREEN);draw.text((220,832),f"ещё гол  •  λ {lam:.2f}  •  {sources}/3 источника",font=_font(25,True),fill=TEXT)
    elif win:
        draw.line((85,758,995,758),fill=LINE,width=2);_center(draw,"✅ ПРОГНОЗ ПОДТВЕРЖДЁН",805,_font(34,True),GREEN)
    _center(draw,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",940,_font(24,True),MUTED)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
