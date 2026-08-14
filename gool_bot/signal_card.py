"""Premium Telegram PNG cards for GOOL actionable LIVE signals."""
from __future__ import annotations
from io import BytesIO
import logging,re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card")

W=1080
BG=(7,12,20); PANEL=(15,24,38); PANEL2=(20,30,46); TEXT=(246,248,252); MUTED=(154,168,190)
GOLD=(255,181,45); GREEN=(87,210,119); BLUE=(52,159,255); LINE=(45,62,86)

def _font(size:int,bold:bool=False):
    paths=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for path in paths:
        try:return ImageFont.truetype(path,size)
        except OSError:pass
    return ImageFont.load_default()
def _fields(record):
    out={}
    for token in record.split("¬"):
        if "÷" in token:k,v=token.split("÷",1);out.setdefault(k,v)
    return out
def _logo_names(event_id):
    body=_feed("f_1_0_0_en_1");needle=f"AA÷{event_id}¬"
    if not body or needle not in body:return "",""
    for chunk in body.split("~"):
        if needle in chunk:
            f=_fields(chunk);return f.get("OA",""),f.get("OB","")
    return "",""
def _download_logo(filename,size=120):
    if not filename:return None
    try:
        r=requests.get(f"https://static.flashscore.com/res/image/data/{filename}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.ok:
            im=Image.open(BytesIO(r.content)).convert("RGBA");im.thumbnail((size,size),Image.Resampling.LANCZOS);return im
    except Exception:pass
    return None
def _initials(name):
    w=re.findall(r"[A-Za-zА-Яа-я0-9]+",name);return "".join(x[0] for x in w[:2]).upper() if w else "?"
def _badge(img,draw,x,y,logo,name,won=False):
    r=68;glow=GREEN if won else (30,98,166)
    draw.ellipse((x-r-5,y-r-5,x+r+5,y+r+5),fill=(9,21,35),outline=glow,width=3)
    draw.ellipse((x-r,y-r,x+r,y+r),fill=(28,40,58),outline=LINE,width=2)
    if logo:img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
    else:
        t=_initials(name);f=_font(34,True);b=draw.textbbox((0,0),t,font=f);draw.text((x-(b[2]-b[0])/2,y-(b[3]-b[1])/2-3),t,font=f,fill=TEXT)
def _fit(draw,text,width,start=38,bold=True):
    for s in range(start,19,-2):
        f=_font(s,bold)
        if draw.textbbox((0,0),text,font=f)[2]<=width:return f
    return _font(20,bold)
def _center(draw,text,y,font,fill):
    b=draw.textbbox((0,0),text,font=font);draw.text(((W-(b[2]-b[0]))/2,y),text,font=font,fill=fill)
def _best(recs):
    recs=recs or [];return next((r for r in recs if r.get("best_bet")),None) or next((r for r in recs if r.get("full_match_best")),None) or next((r for r in recs if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)
def _pair(stats,key):
    try:a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
    except Exception:return 0.0,0.0
def _reason(match,pressure,recs,probabilities):
    stats=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {};minute=int(getattr(match,"minute",0) or 0);goals=int(getattr(match,"home_score",0) or 0)+int(getattr(match,"away_score",0) or 0)
    shots=sum(_pair(stats,"shots"));sot=sum(_pair(stats,"shots_on_target"));xg=sum(_pair(stats,"xg"));p1=int((probabilities or {}).get("one_goal",0) or 0);p2=int((probabilities or {}).get("two_goals",0) or 0);reasons=[]
    if minute<=25 and goals>=2:reasons.append("Матч начался результативно: команды быстро обменялись голами.")
    elif goals>=3:reasons.append("Матч уже результативный, а модель всё ещё ждёт продолжения.")
    if sot>=6 or shots>=18:reasons.append("Темп высокий: команды регулярно доводят атаки до ударов.")
    elif xg>=1.6:reasons.append("По качеству моментов игра остаётся опасной для ворот.")
    if p1>=75 and len(reasons)<2:reasons.append(f"Шанс ещё одного гола до конца матча — {p1}%.")
    if p2>=55 and len(reasons)<2:reasons.append(f"Вероятность ещё двух голов — {p2}%.")
    if _best(recs) and len(reasons)<2:reasons.append("LIVE-рынок подтверждает продолжение результативности.")
    if not reasons:reasons.append("Сигнал подтверждён LIVE-моделью, историей команд и рынком.")
    return " ".join(reasons[:2])
def _draw_header(draw,accent,win):
    draw.rounded_rectangle((24,20,W-24,105),24,fill=PANEL,outline=LINE,width=2);draw.text((54,43),"GOOL AI",font=_font(32,True),fill=TEXT)
    tag="SIGNAL WON" if win else "LIVE SIGNAL";tf=_font(26,True);tb=draw.textbbox((0,0),tag,font=tf);draw.rounded_rectangle((W-250,37,W-48,89),18,fill=(31,43,60),outline=accent,width=2);draw.text((W-149-(tb[2]-tb[0])/2,49),tag,font=tf,fill=accent)
def _draw_match(img,draw,match,accent,won=False):
    hn,an=_logo_names(getattr(match,"event_id",""));hl=_download_logo(hn);al=_download_logo(an);_badge(img,draw,190,320,hl,match.home,won);_badge(img,draw,W-190,320,al,match.away,won)
    draw.rounded_rectangle((390,235,690,405),30,fill=(10,20,32),outline=GREEN if won else LINE,width=2);_center(draw,"● LIVE",247,_font(24,True),GREEN);_center(draw,f"{match.home_score} : {match.away_score}",286,_font(74,True),TEXT)
    minute="ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'";_center(draw,minute,363,_font(28,True),accent)
    hf=_fit(draw,match.home,330,36);af=_fit(draw,match.away,330,36);hb=draw.textbbox((0,0),match.home,font=hf);ab=draw.textbbox((0,0),match.away,font=af);draw.text((190-(hb[2]-hb[0])/2,420),match.home,font=hf,fill=TEXT);draw.text((W-190-(ab[2]-ab[0])/2,420),match.away,font=af,fill=TEXT)
    league=getattr(match,"league","") or "LIVE FOOTBALL";lf=_fit(draw,league,850,24,False);_center(draw,league,474,lf,MUTED)
def _draw_stat_card(draw,probs):
    draw.rounded_rectangle((55,735,1025,885),28,fill=PANEL,outline=LINE,width=2);rows=[]
    if probs.get("first_half_goal") is not None:rows.append(("ГОЛ ДО ПЕРЕРЫВА",int(probs["first_half_goal"])))
    rows.append(("ЕЩЁ 1 ГОЛ ДО КОНЦА",int(probs.get("one_goal",0))));rows.append(("ЕЩЁ 2 ГОЛА ДО КОНЦА",int(probs.get("two_goals",0))));xs=[300,780] if len(rows)==2 else [195,540,885]
    for i,(label,val) in enumerate(rows):
        x=xs[i]
        if i:draw.line((x-155,760,x-155,860),fill=LINE,width=2)
        lf=_fit(draw,label,270,20,True);b=draw.textbbox((0,0),label,font=lf);draw.text((x-(b[2]-b[0])/2,770),label,font=lf,fill=MUTED);vf=_font(38,True);vb=draw.textbbox((0,0),f"{val}%",font=vf);draw.text((x-(vb[2]-vb[0])/2,815),f"{val}%",font=vf,fill=GREEN)
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind:str="entry",master:float|None=None,probabilities:dict|None=None)->bytes:
    win=kind=="goal";accent=GREEN if win else GOLD;H=790 if win else 1120;img=Image.new("RGBA",(W,H),BG+(255,));draw=ImageDraw.Draw(img);_draw_header(draw,accent,win);_center(draw,"ЗАХОД!" if win else "МОЖНО ЗАХОДИТЬ",132,_font(52,True),accent);_draw_match(img,draw,match,accent,win)
    if win:
        # Result card intentionally contains no old rating, market or probabilities: the entry is closed.
        draw.rounded_rectangle((70,540,1010,690),30,fill=(9,24,25),outline=GREEN,width=3)
        draw.ellipse((105,575,195,665),fill=(11,35,31),outline=GREEN,width=3);_center_tick_x=150
        draw.line((_center_tick_x-20,620,_center_tick_x-4,638),fill=GREEN,width=8);draw.line((_center_tick_x-4,638,_center_tick_x+25,602),fill=GREEN,width=8)
        draw.text((235,570),"✓ ГОЛ ПОДТВЕРЖДЁН",font=_font(37,True),fill=GREEN);draw.line((235,620,925,620),fill=(36,91,66),width=2);draw.text((235,642),"Сигнал успешно отработал",font=_font(25,False),fill=TEXT);footer=735
    else:
        probs=probabilities or {};p=int(round(float(master if master is not None else getattr(pressure,"score",0) or 0)));best=_best(recs);draw.rounded_rectangle((55,535,1025,705),28,fill=PANEL2,outline=LINE,width=2);draw.line((540,558,540,682),fill=LINE,width=2);draw.text((105,565),"РЕЙТИНГ GOOL AI",font=_font(22,True),fill=MUTED);draw.text((105,605),f"{p}/100",font=_font(48,True),fill=GOLD);grade="СИЛЬНЫЙ СИГНАЛ" if p>=80 else "ХОРОШИЙ СИГНАЛ" if p>=70 else "РАБОЧИЙ СИГНАЛ";draw.text((105,660),grade,font=_font(20,True),fill=GREEN);draw.text((650,565),"LIVE РЫНОК",font=_font(22,True),fill=MUTED)
        if best:draw.text((650,606),f"ТБ {float(best['line']):g}  •  {float(best['odd']):.2f}",font=_font(40,True),fill=TEXT);draw.text((650,660),str(best.get("source") or "LIVE"),font=_font(22,True),fill=GREEN)
        else:draw.text((650,620),"КЭФ НЕ НАЙДЕН",font=_font(28,True),fill=MUTED)
        _draw_stat_card(draw,probs);draw.rounded_rectangle((55,910,1025,1035),28,fill=PANEL,outline=LINE,width=2);draw.text((95,938),"ПОЧЕМУ МОЖНО ЗАХОДИТЬ",font=_font(23,True),fill=GOLD);reason=_reason(match,pressure,recs,probs);lines=textwrap.wrap(reason,width=78)[:2];yy=978
        for line in lines:draw.text((95,yy),line,font=_font(22,False),fill=TEXT);yy+=32
        footer=1070
    _center(draw,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",footer,_font(21,True),MUTED);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
