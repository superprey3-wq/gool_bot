from __future__ import annotations
from io import BytesIO
import re,requests
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from live_engine import _feed

GOLD=(246,181,48);BLUE=(40,158,255);PURPLE=(171,105,255);WHITE=(246,248,252);MUTED=(157,170,192);GREEN=(82,220,116);BG=(4,9,17);PANEL=(10,18,31)

def F(size,bold=False):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
        try:return ImageFont.truetype(p,size)
        except:pass
    return ImageFont.load_default()
def fields(rec):
    out={}
    for t in rec.split("¬"):
        if "÷" in t:k,v=t.split("÷",1);out.setdefault(k,v)
    return out
def logos(eid):
    try:body=_feed("f_1_0_0_en_1") or ""
    except:return "",""
    needle=f"AA÷{eid}¬"
    for c in body.split("~"):
        if needle in c:
            f=fields(c);return f.get("OA",""),f.get("OB","")
    return "",""
def dl(name):
    if not name:return None
    try:
        r=requests.get(f"https://static.flashscore.com/res/image/data/{name}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.ok:return Image.open(BytesIO(r.content)).convert("RGBA")
    except:pass
    return None
def fit(draw,text,maxw,size=42,bold=True):
    for s in range(size,17,-2):
        ft=F(s,bold)
        if draw.textbbox((0,0),str(text),font=ft)[2]<=maxw:return ft
    return F(18,bold)
def center(draw,text,y,font,fill,w):
    b=draw.textbbox((0,0),str(text),font=font);draw.text(((w-(b[2]-b[0]))/2,y),str(text),font=font,fill=fill)
def glow_round(base,box,accent,radius=28,width=3):
    glow=Image.new("RGBA",base.size,(0,0,0,0));g=ImageDraw.Draw(glow)
    for e,a in [(12,45),(7,75),(3,120)]:g.rounded_rectangle((box[0]-e,box[1]-e,box[2]+e,box[3]+e),radius+e,outline=accent+(a,),width=3)
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)));ImageDraw.Draw(base).rounded_rectangle(box,radius,fill=PANEL+(255,),outline=accent,width=width)
def crest(base,im,cx,cy,accent,size=165):
    d=ImageDraw.Draw(base);r=size//2;d.ellipse((cx-r-8,cy-r-8,cx+r+8,cy+r+8),outline=accent,width=3);d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(12,23,38),outline=accent,width=2)
    if im:
        bb=im.getbbox();im=im.crop(bb) if bb else im;s=min((size-20)/max(1,im.width),(size-20)/max(1,im.height));im=im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS);base.alpha_composite(im,(cx-im.width//2,cy-im.height//2))
def kind_info(engine):
    if engine in {"first_half_goal","first_half","ht_hunter","ht"}:return BLUE,"GOOL • 1-Й ТАЙМ","ГОЛ ДО ПЕРЕРЫВА","ТБ текущего 1-го тайма"
    if engine in {"second_half_over15","second_half"}:return PURPLE,"GOOL • 2-Й ТАЙМ","ТБ1.5 ВО 2-М ТАЙМЕ","Решение в перерыве"
    return GOLD,"GOOL CORE","ГЛАВНЫЙ LIVE-СИГНАЛ","Лучший рынок матча"
def _val(delta,key,fmt="int"):
    v=delta.get(key)
    if v is None:return "—"
    try:return f"{float(v):.2f}" if fmt=="float" else f"{int(round(float(v)))}"
    except:return "—"
def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
    delta=delta or {};timing=delta.get("_timing") or {};accent,title,subtitle,market_label=kind_info(engine)
    if result is not None:return render_result_card(match,engine,result)
    W,H=1200,1110;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow_round(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img)
    d.text((55,42),title,font=F(38,True),fill=accent);d.text((57,91),subtitle,font=F(24,True),fill=WHITE);d.rounded_rectangle((930,47,1145,103),16,outline=accent,width=2);d.text((962,62),"LIVE SIGNAL",font=F(22,True),fill=accent)
    hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),195,300,accent,175);crest(img,dl(an),1005,300,accent,175);d=ImageDraw.Draw(img);glow_round(img,(430,210,770,395),accent,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",252,F(70,True),WHITE,W);status="ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'";center(d,status,337,F(32,True),accent,W)
    for x,n in ((195,match.home),(1005,match.away)):
        f=fit(d,n,340,33);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,420),n,font=f,fill=WHITE)
    center(d,getattr(match,"league","") or "LIVE FOOTBALL",472,F(22),MUTED,W)
    glow_round(img,(55,525,1145,675),accent,22,2);d=ImageDraw.Draw(img);d.text((90,555),"РЕЙТИНГ СТРАТЕГИИ",font=F(20,True),fill=MUTED);d.text((90,592),f"{int(round(score))}/100",font=F(44,True),fill=accent);d.line((560,548,560,650),fill=(65,82,105),width=2);d.text((620,555),"КОНКРЕТНАЯ СТАВКА",font=F(20,True),fill=MUTED);d.text((620,592),market_label,font=fit(d,market_label,470,29,True),fill=WHITE);d.text((620,630),f"КЭФ • {float(odd):.2f}" if odd and float(odd)>1 else "LIVE-кэф не найден",font=F(23,True),fill=GREEN if odd and float(odd)>1 else MUTED)
    labels=[("xG",_val(delta,"xg","float")),("xGoT",_val(delta,"xgot","float")),("УДАРЫ",_val(delta,"shots")),("В СТВОР",_val(delta,"shots_on_target")),("BIG CHANCES",_val(delta,"big_chances")),("В ШТРАФНОЙ",_val(delta,"shots_inside_box"))]
    y=715;gap=12;cw=(1090-gap*2)/3
    for i,(lab,val) in enumerate(labels):
        row=i//3;col=i%3;xa=55+col*(cw+gap);ya=y+row*110;d.rounded_rectangle((xa,ya,xa+cw,ya+92),16,fill=(9,18,31),outline=accent,width=1);d.text((xa+16,ya+14),lab,font=F(17,True),fill=MUTED);d.text((xa+16,ya+47),val,font=F(28,True),fill=WHITE)
    why_y=950;d.text((75,why_y),"ПОЧЕМУ СИГНАЛ",font=F(23,True),fill=accent);why="Свежая LIVE-статистика и рынок подтверждают сценарий."
    if engine=="second_half_over15":why="Первый тайм дал достаточно темпа и качества моментов для ТБ1.5 во 2-м тайме."
    if timing.get("pct") is not None:why+=f" Профиль лиги в текущем сегменте: {float(timing['pct']):.0f}%."
    d.text((75,why_y+42),why,font=fit(d,why,1040,22,False),fill=WHITE);center(d,"GOOL AI • LIVE FOOTBALL ANALYTICS",1050,F(19,True),MUTED,W)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
def render_result_card(match,engine,result):
    accent,title,subtitle,_=kind_info(engine);W,H=1200,790;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow_round(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img);d.text((55,42),title,font=F(34,True),fill=accent);headline="ЗАХОД!" if result=="win" else "НЕ ЗАШЛО";center(d,headline,120,F(68,True),GREEN if result=="win" else accent,W);hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),190,365,accent,175);crest(img,dl(an),1010,365,accent,175);glow_round(img,(425,270,775,455),accent,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",310,F(72,True),WHITE,W);center(d,f"{match.minute}'",393,F(32,True),accent,W);center(d,"Ставка закрыта по правилам стратегии",610,F(25),WHITE,W);center(d,"GOOL AI • LIVE FOOTBALL ANALYTICS",730,F(19,True),MUTED,W);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
