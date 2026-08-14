"""Premium Telegram PNG cards for GOOL actionable LIVE signals."""
from __future__ import annotations
from io import BytesIO
import logging,re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card")
W,H=1080,1200; BG=(10,15,24); PANEL=(22,29,42); TEXT=(246,248,252); MUTED=(153,165,184); GOLD=(255,187,56); GREEN=(65,205,132); LINE=(49,61,80)

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
def _pair(stats,key):
    try:
        a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
    except Exception:return 0.0,0.0
def _reason(match,pressure,recs,probabilities):
    """Build two short factual sentences only from data actually available."""
    stats=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {}
    minute=int(getattr(match,"minute",0) or 0);goals=int(getattr(match,"home_score",0) or 0)+int(getattr(match,"away_score",0) or 0)
    shots=sum(_pair(stats,"shots"));sot=sum(_pair(stats,"shots_on_target"));xg=sum(_pair(stats,"xg"))
    p1=int((probabilities or {}).get("one_goal",0) or 0);p2=int((probabilities or {}).get("two_goals",0) or 0)
    reasons=[]
    if minute<=25 and goals>=2:reasons.append("Матч началcя очень результативно: команды быстро обменялись голами.")
    elif goals>=3:reasons.append("Матч уже результативный, а модель всё ещё ждёт продолжения.")
    if sot>=6 or shots>=18:reasons.append("Темп высокий: команды регулярно доводят атаки до ударов.")
    elif xg>=1.6:reasons.append("По качеству созданных моментов игра остаётся опасной для ворот.")
    if p1>=75 and len(reasons)<2:reasons.append(f"GOOL оценивает шанс ещё одного гола до конца матча в {p1}%.")
    if p2>=55 and len(reasons)<2:reasons.append(f"Даже вероятность ещё двух голов остаётся высокой — {p2}%.")
    best=_best(recs)
    if best and len(reasons)<2:reasons.append("LIVE-рынок также оставляет рабочую линию на продолжение результативности.")
    if not reasons:reasons.append("Сигнал подтверждён совокупностью LIVE-модели, истории команд и рынка.")
    return " ".join(reasons[:2])
def _draw_match(img,draw,match,accent):
    hn,an=_logo_names(getattr(match,"event_id",""));hl=_download_logo(hn);al=_download_logo(an)
    _badge(img,draw,190,335,hl,match.home);_badge(img,draw,W-190,335,al,match.away)
    _center(draw,f"{match.home_score} : {match.away_score}",278,_font(82,True),TEXT)
    minute="ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'";_center(draw,minute,380,_font(30,True),accent)
    hf=_fit(draw,match.home,350);af=_fit(draw,match.away,350);hb=draw.textbbox((0,0),match.home,font=hf);ab=draw.textbbox((0,0),match.away,font=af)
    draw.text((190-(hb[2]-hb[0])/2,430),match.home,font=hf,fill=TEXT);draw.text((W-190-(ab[2]-ab[0])/2,430),match.away,font=af,fill=TEXT)
    league=getattr(match,"league","") or "LIVE FOOTBALL";lf=_fit(draw,league,850,25,False);_center(draw,league,490,lf,MUTED)
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind:str="entry",master:float|None=None,probabilities:dict|None=None)->bytes:
    win=kind=="goal";accent=GREEN if win else GOLD
    img=Image.new("RGBA",(W,H),BG+(255,));draw=ImageDraw.Draw(img)
    draw.rounded_rectangle((38,34,W-38,128),28,fill=PANEL,outline=LINE,width=2);draw.text((72,60),"GOOL AI",font=_font(34,True),fill=TEXT)
    tag="SIGNAL WON" if win else "LIVE SIGNAL";tb=draw.textbbox((0,0),tag,font=_font(28,True));draw.text((W-72-(tb[2]-tb[0]),64),tag,font=_font(28,True),fill=accent)
    _center(draw,"СИГНАЛ ЗАШЁЛ — ГОЛ!" if win else "МОЖНО ЗАХОДИТЬ",165,_font(48,True),accent);_draw_match(img,draw,match,accent)
    if win:
        draw.rounded_rectangle((95,585,985,830),34,fill=PANEL,outline=LINE,width=2);_center(draw,"✅ ПРОГНОЗ УСПЕШНО ОТРАБОТАЛ",645,_font(38,True),GREEN);_center(draw,"Новый анализ матча продолжается внутри GOOL AI",720,_font(25,False),MUTED)
    else:
        probs=probabilities or {};p=int(round(float(master if master is not None else getattr(pressure,"score",0) or 0)))
        draw.rounded_rectangle((50,550,1030,910),30,fill=PANEL,outline=LINE,width=2);draw.text((82,582),"РЕЙТИНГ",font=_font(21,True),fill=MUTED);draw.text((82,615),f"{p}/100",font=_font(48,True),fill=accent)
        best=_best(recs);draw.text((570,582),"LIVE РЫНОК",font=_font(21,True),fill=MUTED)
        if best:draw.text((570,620),f"ТБ {float(best['line']):g}  •  {float(best['odd']):.2f}",font=_font(39,True),fill=TEXT);draw.text((570,675),str(best.get("source") or "LIVE"),font=_font(22,True),fill=GREEN)
        else:draw.text((570,630),"КЭФ НЕ НАЙДЕН",font=_font(29,True),fill=MUTED)
        draw.line((82,735,998,735),fill=LINE,width=2);rows=[]
        if probs.get("first_half_goal") is not None:rows.append(("ГОЛ ДО ПЕРЕРЫВА",int(probs["first_half_goal"])))
        rows.append(("ЕЩЁ 1 ГОЛ ДО КОНЦА МАТЧА",int(probs.get("one_goal",0))));rows.append(("ЕЩЁ 2 ГОЛА ДО КОНЦА МАТЧА",int(probs.get("two_goals",0))))
        y=770
        for label,val in rows:
            draw.text((82,y),label,font=_font(22,True),fill=MUTED);vb=draw.textbbox((0,0),f"{val}%",font=_font(32,True));draw.text((998-(vb[2]-vb[0]),y-5),f"{val}%",font=_font(32,True),fill=GREEN);y+=52
        # Human-readable rationale inside the same image.
        draw.rounded_rectangle((50,935,1030,1110),26,fill=PANEL,outline=LINE,width=2);draw.text((82,962),"🧠 ПОЧЕМУ МОЖНО ЗАХОДИТЬ",font=_font(22,True),fill=GOLD)
        reason=_reason(match,pressure,recs,probs);lines=textwrap.wrap(reason,width=70)[:3];yy=1005
        for line in lines:draw.text((82,yy),line,font=_font(23,False),fill=TEXT);yy+=34
    _center(draw,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",1145,_font(24,True),MUTED)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
