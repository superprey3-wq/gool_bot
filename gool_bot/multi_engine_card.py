from __future__ import annotations
from io import BytesIO
import re,requests
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from live_engine import _feed

GOLD=(246,181,48);BLUE=(40,158,255);RED=(255,61,67);WHITE=(246,248,252);MUTED=(157,170,192);GREEN=(82,220,116);BG=(4,9,17);PANEL=(10,18,31)

def F(size,bold=False):
    paths=["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    for p in paths:
        try:return ImageFont.truetype(p,size)
        except:pass
    return ImageFont.load_default()

def fields(rec):
    out={}
    for t in rec.split("¬"):
        if "÷" in t:
            k,v=t.split("÷",1);out.setdefault(k,v)
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
    for s in range(size,18,-2):
        ft=F(s,bold)
        if draw.textbbox((0,0),str(text),font=ft)[2]<=maxw:return ft
    return F(18,bold)

def center(draw,text,y,font,fill,w):
    b=draw.textbbox((0,0),str(text),font=font);draw.text(((w-(b[2]-b[0]))/2,y),str(text),font=font,fill=fill)

def glow_round(base,box,accent,radius=28,width=3):
    glow=Image.new("RGBA",base.size,(0,0,0,0));g=ImageDraw.Draw(glow)
    for e,a in [(13,55),(8,85),(4,120)]:g.rounded_rectangle((box[0]-e,box[1]-e,box[2]+e,box[3]+e),radius+e,outline=accent+(a,),width=3)
    glow=glow.filter(ImageFilter.GaussianBlur(5));base.alpha_composite(glow)
    d=ImageDraw.Draw(base);d.rounded_rectangle(box,radius,fill=PANEL+(255,),outline=accent,width=width)

def crest(base,im,cx,cy,accent,size=165):
    d=ImageDraw.Draw(base)
    for r,a in [(size//2+16,45),(size//2+9,80),(size//2+3,150)]:d.ellipse((cx-r,cy-r,cx+r,cy+r),outline=accent+(a,),width=3)
    d.ellipse((cx-size//2,cy-size//2,cx+size//2,cy+size//2),fill=(12,23,38,255),outline=accent,width=3)
    if im:
        bb=im.getbbox(); im=im.crop(bb) if bb else im
        scale=min((size-18)/max(1,im.width),(size-18)/max(1,im.height));im=im.resize((max(1,int(im.width*scale)),max(1,int(im.height*scale))),Image.Resampling.LANCZOS)
        base.alpha_composite(im,(cx-im.width//2,cy-im.height//2))

def kind_info(engine):
    if engine in {"core","main","primary"}:return "core",GOLD,"GOOL CORE","ГЛАВНЫЙ СИГНАЛ"
    if engine in {"first_half","ht_hunter","ht"}:return "ht",BLUE,"GOOL HT HUNTER","ГОЛ ДО ПЕРЕРЫВА"
    return "risk",RED,"GOOL LATE RISK","ПОЗДНИЙ ГОЛ"

def timing_strip(d,x1,y1,x2,accent,timing):
    segs=(timing or {}).get("segments") or {}
    labels=["0-15'","16-30'","31-45'","46-60'","61-75'","76-90'"]
    keys=["0-15","16-30","31-45","46-60","61-75","76-90"]
    d.text((x1,y1-34),"ТАЙМИНГ ГОЛОВ (ЛИГА)",font=F(23,True),fill=accent)
    w=(x2-x1)/6
    active=(timing or {}).get("segment")
    for i,(lab,key) in enumerate(zip(labels,keys)):
        xa=int(x1+i*w);xb=int(x1+(i+1)*w)
        fill=(18,33,53) if key!=active else tuple(min(255,int(c*.38)) for c in accent)
        d.rectangle((xa,y1,xb,y1+70),fill=fill,outline=accent,width=1)
        pct=segs.get(key)
        tf=F(17,True);pf=F(22,True)
        tb=d.textbbox((0,0),lab,font=tf);d.text((xa+(xb-xa-(tb[2]-tb[0]))/2,y1+8),lab,font=tf,fill=WHITE)
        val="—" if pct is None else f"{float(pct):.0f}%";pb=d.textbbox((0,0),val,font=pf);d.text((xa+(xb-xa-(pb[2]-pb[0]))/2,y1+37),val,font=pf,fill=accent if key==active else WHITE)

def _odd(v):
    try:
        x=float(v);return f"{x:.2f}" if x>1 else "—"
    except:return "—"

def odds_strip(d,x1,y1,x2,accent,data,minute):
    data=data or {};d.text((x1,y1-34),"1XBET LIVE • КОЭФФИЦИЕНТЫ",font=F(23,True),fill=accent)
    target=data.get("target")
    # Three compact cells: 1H goal / match total / BTTS.
    if int(minute or 0)<45:
        lab1=f"1-Й ТАЙМ • ТБ {target:g}" if isinstance(target,(int,float)) else "1-Й ТАЙМ"
        val1=_odd(data.get("half_over"))
    else:
        lab1="ЕЩЁ 1 ГОЛ"
        val1=_odd(data.get("next_over"))
    ml=data.get("main_line")
    lab2=f"ТОТАЛ МАТЧА • {ml:g}" if isinstance(ml,(int,float)) else "ТОТАЛ МАТЧА"
    if ml is not None:
        val2=f"ТБ {_odd(data.get('main_over'))}  •  ТМ {_odd(data.get('main_under'))}"
    else:val2="—"
    val3=f"ДА {_odd(data.get('btts_yes'))}  •  НЕТ {_odd(data.get('btts_no'))}"
    cards=[(lab1,val1),(lab2,val2),("ОБЕ ЗАБЬЮТ",val3)]
    gap=14;w=(x2-x1-gap*2)/3
    for i,(lab,val) in enumerate(cards):
        xa=int(x1+i*(w+gap));xb=int(xa+w)
        d.rounded_rectangle((xa,y1,xb,y1+82),16,fill=(9,18,31),outline=accent,width=1)
        d.text((xa+16,y1+13),lab,font=fit(d,lab,w-32,18,True),fill=MUTED)
        d.text((xa+16,y1+43),val,font=fit(d,val,w-32,25,True),fill=WHITE if val!="—" else MUTED)

def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
    delta=delta or {};timing=delta.get("_timing") or {};xbet=delta.get("_xbet") or {}
    kind,accent,title,subtitle=kind_info(engine)
    if result is not None:return render_result_card(match,kind,accent,title,result)
    W,H=1200,1200
    img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img)
    glow_round(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img)
    icon="♛" if kind=="core" else "◉" if kind=="ht" else "⚡"
    d.text((55,42),icon,font=F(42,True),fill=accent);d.text((110,42),title,font=F(42,True),fill=accent);d.text((112,94),subtitle,font=F(23,True),fill=WHITE)
    d.rounded_rectangle((930,48,1145,105),16,outline=accent,width=2);d.text((965,63),"LIVE SIGNAL",font=F(22,True),fill=accent)
    hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),195,310,accent,185);crest(img,dl(an),1005,310,accent,185);d=ImageDraw.Draw(img)
    glow_round(img,(430,215,770,405),accent,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",257,F(72,True),WHITE,W);center(d,f"{match.minute}'",343,F(34,True),accent,W)
    hf=fit(d,match.home,340,34);af=fit(d,match.away,340,34);hb=d.textbbox((0,0),match.home,font=hf);ab=d.textbbox((0,0),match.away,font=af);d.text((195-(hb[2]-hb[0])/2,430),match.home,font=hf,fill=WHITE);d.text((1005-(ab[2]-ab[0])/2,430),match.away,font=af,fill=WHITE)
    center(d,getattr(match,"league","") or "LIVE FOOTBALL",482,F(23),MUTED,W)
    glow_round(img,(55,535,1145,675),accent,22,2);d=ImageDraw.Draw(img);d.text((90,566),"РЕЙТИНГ GOOL AI",font=F(22,True),fill=MUTED);d.text((90,600),f"{int(round(score))}/100",font=F(42,True),fill=accent);d.line((575,555,575,655),fill=(65,82,105),width=2);d.text((640,566),"LIVE РЫНОК",font=F(22,True),fill=MUTED);d.text((640,605),(f"КЭФ • {float(odd):.2f}" if odd and float(odd)>1 else "НЕТ ДАННЫХ"),font=F(36,True),fill=WHITE)
    vals=[("xG (10')",delta.get("xg")),("УДАРЫ",delta.get("shots")),("В СТВОР",delta.get("shots_on_target")),("ОПАСНЫЕ АТАКИ",delta.get("touches_box"))]
    x=55;y=700;cell=272
    for i,(lab,val) in enumerate(vals):
        xa=x+i*cell;d.rounded_rectangle((xa,y,xa+250,y+105),18,fill=(9,18,31),outline=accent,width=1);d.text((xa+18,y+18),lab,font=F(18,True),fill=MUTED);d.text((xa+18,y+53),("—" if val is None else f"+{float(val):.2f}" if lab.startswith("xG") else f"+{int(float(val))}"),font=F(29,True),fill=WHITE)
    odds_strip(d,65,855,1135,accent,xbet,getattr(match,"minute",0))
    why_y=985;d.text((80,why_y),"ПОЧЕМУ СИГНАЛ",font=F(25,True),fill=accent)
    why="Свежий LIVE-тренд подтверждает давление"
    if timing.get("pct") is not None:why+=f" • {timing.get('segment')} в лиге: {float(timing['pct']):.0f}%"
    d.text((80,why_y+43),why,font=fit(d,why,1030,25,False),fill=WHITE);d.text((80,why_y+82),"Один сигнал → один результат",font=F(22),fill=MUTED)
    center(d,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",1130,F(20,True),MUTED,W)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()

def render_result_card(match,kind,accent,title,result):
    W,H=1200,820;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow_round(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img)
    d.text((55,42),title,font=F(34,True),fill=accent);d.rounded_rectangle((930,42,1145,96),16,outline=accent,width=2);d.text((958,56),"SIGNAL WON" if result=="win" else "SIGNAL LOST",font=F(21,True),fill=accent)
    headline="ЗАХОД!" if result=="win" else "НЕ ЗАШЁЛ";center(d,headline,115,F(72,True),accent,W)
    hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),190,370,accent,185);crest(img,dl(an),1010,370,accent,185);glow_round(img,(425,265,775,470),accent,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",310,F(74,True),WHITE,W);center(d,f"{match.minute}'",400,F(34,True),accent,W)
    hf=fit(d,match.home,320,33);af=fit(d,match.away,320,33);hb=d.textbbox((0,0),match.home,font=hf);ab=d.textbbox((0,0),match.away,font=af);d.text((190-(hb[2]-hb[0])/2,490),match.home,font=hf,fill=WHITE);d.text((1010-(ab[2]-ab[0])/2,490),match.away,font=af,fill=WHITE);center(d,getattr(match,"league","") or "LIVE FOOTBALL",545,F(22),MUTED,W)
    glow_round(img,(80,605,1120,720),accent,22,2);d=ImageDraw.Draw(img);d.text((125,632),"⚽  ✓  ГОЛ ПОДТВЕРЖДЁН" if result=="win" else "✕  СИГНАЛ ЗАКРЫТ",font=F(36,True),fill=accent);d.text((125,680),"Сигнал успешно отработал" if result=="win" else "Гола в заданном окне не было",font=F(24),fill=WHITE)
    center(d,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",760,F(19,True),MUTED,W)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
