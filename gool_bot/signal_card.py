"""Premium Telegram PNG cards for GOOL actionable LIVE signals."""
from __future__ import annotations
from io import BytesIO
import logging,re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card")
W=1080;BG=(10,15,24);PANEL=(22,29,42);TEXT=(246,248,252);MUTED=(153,165,184);GOLD=(255,187,56);GREEN=(65,205,132);LINE=(49,61,80)
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
def _badge(img,draw,x,y,logo,name):
    r=64;draw.ellipse((x-r,y-r,x+r,y+r),fill=(31,40,56),outline=LINE,width=3)
    if logo:img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
    else:
        t=_initials(name);f=_font(36,True);b=draw.textbbox((0,0),t,font=f);draw.text((x-(b[2]-b[0])/2,y-(b[3]-b[1])/2-3),t,font=f,fill=TEXT)
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
def _draw_match(img,draw,match,accent,base_y=300):
    hn,an=_logo_names(getattr(match,"event_id",""));hl=_download_logo(hn);al=_download_logo(an)
    _badge(img,draw,175,base_y,hl,match.home);_badge(img,draw,W-175,base_y,al,match.away)
    _center(draw,f"{match.home_score} : {match.away_score}",base_y-52,_font(76,True),TEXT)
    minute="ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'";_center(draw,minute,base_y+54,_font(30,True),accent)
    hf=_fit(draw,match.home,360);af=_fit(draw,match.away,360);hb=draw.textbbox((0,0),match.home,font=hf);ab=draw.textbbox((0,0),match.away,font=af)
    draw.text((175-(hb[2]-hb[0])/2,base_y+100),match.home,font=hf,fill=TEXT);draw.text((W-175-(ab[2]-ab[0])/2,base_y+100),match.away,font=af,fill=TEXT)
    league=getattr(match,"league","") or "LIVE FOOTBALL";lf=_fit(draw,league,850,25,False);_center(draw,league,base_y+155,lf,MUTED)
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind:str="entry",master:float|None=None,probabilities:dict|None=None)->bytes:
    win=kind=="goal";accent=GREEN if win else GOLD;H=700 if win else 1080
    img=Image.new("RGBA",(W,H),BG+(255,));draw=ImageDraw.Draw(img)
    draw.rounded_rectangle((38,28,W-38,112),24,fill=PANEL,outline=LINE,width=2);draw.text((70,50),"GOOL AI",font=_font(32,True),fill=TEXT)
    tag="SIGNAL WON" if win else "LIVE SIGNAL";tf=_font(26,True);tb=draw.textbbox((0,0),tag,font=tf);draw.text((W-70-(tb[2]-tb[0]),53),tag,font=tf,fill=accent)
    _center(draw,"ЗАХОД!" if win else "МОЖНО ЗАХОДИТЬ",142,_font(52,True),accent)
    _draw_match(img,draw,match,accent,base_y=315)
    if win:
        draw.rounded_rectangle((120,520,960,610),26,fill=PANEL,outline=LINE,width=2)
        _center(draw,"✅ ЗАХОД!",542,_font(40,True),GREEN)
        footer=652
    else:
        probs=probabilities or {};p=int(round(float(master if master is not None else getattr(pressure,"score",0) or 0)))
        draw.rounded_rectangle((50,520,1030,815),28,fill=PANEL,outline=LINE,width=2)
        draw.text((82,550),"РЕЙТИНГ",font=_font(22,True),fill=MUTED);draw.text((82,584),f"{p}/100",font=_font(50,True),fill=accent)
        best=_best(recs);draw.text((570,550),"LIVE РЫНОК",font=_font(22,True),fill=MUTED)
        if best:
            draw.text((570,586),f"ТБ {float(best['line']):g}  •  {float(best['odd']):.2f}",font=_font(40,True),fill=TEXT);draw.text((570,642),str(best.get("source") or "LIVE"),font=_font(22,True),fill=GREEN)
        else:draw.text((570,596),"КЭФ НЕ НАЙДЕН",font=_font(28,True),fill=MUTED)
        draw.line((82,690,998,690),fill=LINE,width=2);rows=[]
        if probs.get("first_half_goal") is not None:rows.append(("ГОЛ ДО ПЕРЕРЫВА",int(probs["first_half_goal"])))
        rows.append(("ЕЩЁ 1 ГОЛ ДО КОНЦА МАТЧА",int(probs.get("one_goal",0))));rows.append(("ЕЩЁ 2 ГОЛА ДО КОНЦА МАТЧА",int(probs.get("two_goals",0))))
        y=718
        for label,val in rows:
            draw.text((82,y),label,font=_font(22,True),fill=MUTED);vf=_font(32,True);vb=draw.textbbox((0,0),f"{val}%",font=vf);draw.text((998-(vb[2]-vb[0]),y-4),f"{val}%",font=vf,fill=GREEN);y+=46
        draw.rounded_rectangle((50,840,1030,1005),26,fill=PANEL,outline=LINE,width=2)
        draw.text((82,866),"🧠 ПОЧЕМУ МОЖНО ЗАХОДИТЬ",font=_font(22,True),fill=GOLD)
        reason=_reason(match,pressure,recs,probs);lines=textwrap.wrap(reason,width=76)[:3];yy=910
        for line in lines:draw.text((82,yy),line,font=_font(23,False),fill=TEXT);yy+=34
        footer=1032
    _center(draw,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",footer,_font(21,True),MUTED)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
