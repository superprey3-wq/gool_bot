from __future__ import annotations
from io import BytesIO
import re,requests,textwrap
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from live_engine import _feed

GOLD=(246,181,48);BLUE=(45,166,255);PURPLE=(174,112,255);WHITE=(247,249,252);MUTED=(157,171,193);GREEN=(83,220,116);RED=(244,103,103);BG=(4,9,17);PANEL=(10,18,31);LINE=(47,63,86)
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
def crest(base,im,cx,cy,accent,size=160):
    d=ImageDraw.Draw(base);r=size//2;d.ellipse((cx-r-8,cy-r-8,cx+r+8,cy+r+8),outline=accent,width=3);d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(12,23,38),outline=accent,width=2)
    if im:
        bb=im.getbbox();im=im.crop(bb) if bb else im;s=min((size-20)/max(1,im.width),(size-20)/max(1,im.height));im=im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS);base.alpha_composite(im,(cx-im.width//2,cy-im.height//2))
def _val(delta,key,fmt="int"):
    v=delta.get(key)
    if v is None:return "—"
    try:return f"{float(v):.2f}" if fmt=="float" else f"{int(round(float(v)))}"
    except:return "—"
def _sources(market):
    if not market:return "—"
    rows=market.get("source_prices") or []
    if rows:return "  •  ".join(f"{str(x.get('source','LIVE')).split('/')[0]} {float(x.get('odd',0)):.2f}" for x in rows[:3])
    try:return f"LIVE {float(market.get('odd',0)):.2f}"
    except:return "—"
def _status(market):
    s=str((market or {}).get("market_status") or "")
    return {"CONFIRMED":"✓ ПОДТВЕРЖДЕНО","STEAM":"🔥 ПРОГРУЗ","DISAGREE":"⚠ РАСХОЖДЕНИЕ","SINGLE_SOURCE":"1 ИСТОЧНИК","EARLY":"РАННИЙ РЫНОК"}.get(s,s)
def _box(d,xy,title,value,accent):
    d.rounded_rectangle(xy,16,fill=(9,18,31),outline=LINE,width=1);x1,y1,x2,y2=xy;d.text((x1+16,y1+13),title,font=F(16,True),fill=MUTED);d.text((x1+16,y1+44),value,font=fit(d,value,x2-x1-32,26,True),fill=accent)
def _header_text(engine):
    if engine=="first_half_goal":return BLUE,"GOOL • 1-Й ТАЙМ","АНАЛИЗ С 1-Й МИНУТЫ","ОКНО РЕШЕНИЯ 15–25'"
    return PURPLE,"GOOL • 2-Й ТАЙМ","РЕШЕНИЕ В ПЕРЕРЫВЕ","ТБ1.5 ВО 2-М ТАЙМЕ"
def _market_label(engine,market):
    if engine=="first_half_goal":
        try:return f"ТБ {float(market.get('line')):g} В 1-М ТАЙМЕ"
        except:return "ГОЛ ДО ПЕРЕРЫВА"
    return "ТБ 1.5 ВО 2-М ТАЙМЕ"
def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
    delta=delta or {};market=delta.get("_market") or {};timing=delta.get("_timing") or {};accent,title,subtitle,mode=_header_text(engine)
    if result is not None:return render_result_card(match,engine,result)
    W,H=1200,1200;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow_round(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img)
    d.text((55,40),title,font=F(38,True),fill=accent);d.text((57,88),subtitle,font=F(23,True),fill=WHITE);d.rounded_rectangle((900,43,1145,105),17,outline=accent,width=2);d.text((925,59),mode,font=fit(d,mode,200,20,True),fill=accent)
    hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),195,292,accent);crest(img,dl(an),1005,292,accent);glow_round(img,(430,205,770,388),accent,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",246,F(70,True),WHITE,W);center(d,"ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'",331,F(31,True),accent,W)
    for x,n in ((195,match.home),(1005,match.away)):
        f=fit(d,n,340,32);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,407),n,font=f,fill=WHITE)
    center(d,getattr(match,"league","") or "LIVE FOOTBALL",458,F(21),MUTED,W)
    glow_round(img,(55,510,1145,690),accent,22,2);d=ImageDraw.Draw(img);d.text((90,538),"РЕШЕНИЕ СТРАТЕГИИ",font=F(18,True),fill=MUTED);d.text((90,572),"⭐ КОНКРЕТНАЯ СТАВКА",font=F(24,True),fill=accent);label=_market_label(engine,market);d.text((90,614),label,font=fit(d,label,610,34,True),fill=WHITE);d.text((90,655),f"КЭФ {float(odd):.2f}" if odd and float(odd)>1 else "КЭФ НЕ НАЙДЕН",font=F(23,True),fill=GREEN if odd and float(odd)>1 else MUTED);d.text((790,545),"РЕЙТИНГ",font=F(17,True),fill=MUTED);d.text((790,582),f"{int(round(score))}/100",font=F(44,True),fill=accent);d.text((790,637),_status(market) or "LIVE",font=fit(d,_status(market) or "LIVE",310,18,True),fill=GREEN)
    d.text((70,724),"РЫНОК • ПОДТВЕРЖДЕНИЕ",font=F(20,True),fill=accent);d.rounded_rectangle((55,760,1145,835),18,fill=(9,18,31),outline=LINE,width=1);d.text((80,781),_sources(market),font=fit(d,_sources(market),1040,22,True),fill=WHITE)
    labels=[("xG",_val(delta,"xg","float")),("xGoT",_val(delta,"xgot","float")),("УДАРЫ",_val(delta,"shots")),("В СТВОР",_val(delta,"shots_on_target")),("BIG CHANCES",_val(delta,"big_chances")),("В ШТРАФНОЙ",_val(delta,"shots_inside_box"))]
    y=865;gap=12;cw=(1090-gap*2)/3
    for i,(lab,val) in enumerate(labels):
        row=i//3;col=i%3;xa=55+col*(cw+gap);ya=y+row*98;_box(d,(xa,ya,xa+cw,ya+82),lab,val,WHITE)
    why_y=1070;d.text((70,why_y),"ПОЧЕМУ ВХОД",font=F(21,True),fill=accent)
    if engine=="first_half_goal":why="Бот собирает матч с 1-й минуты и допускает вход только в окне 15–25', если темп, качество моментов и рынок совпадают."
    else:why="Решение принимается только в перерыве по всему первому тайму: темп, xG/xGoT, створы и подтверждение рынка ТБ1.5 второго тайма."
    if timing.get("pct") is not None:why+=f" Профиль лиги: {float(timing['pct']):.0f}%."
    yy=1105
    for line in textwrap.wrap(why,width=82)[:2]:d.text((70,yy),line,font=F(18),fill=WHITE);yy+=28
    center(d,"GOOL AI • LIVE FOOTBALL ANALYTICS",1160,F(18,True),MUTED,W);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
def render_result_card(match,engine,result):
    accent,title,_,_=_header_text(engine);W,H=1200,790;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow_round(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img);d.text((55,42),title,font=F(34,True),fill=accent);headline="ЗАШЛО" if result=="win" else "НЕ ЗАШЛО";center(d,headline,120,F(68,True),GREEN if result=="win" else RED,W);hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),190,365,accent,175);crest(img,dl(an),1010,365,accent,175);glow_round(img,(425,270,775,455),accent,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",310,F(72,True),WHITE,W);center(d,f"{match.minute}'",393,F(32,True),accent,W);center(d,"Результат зафиксирован в журнале стратегии",610,F(25),WHITE,W);center(d,"GOOL AI • LIVE FOOTBALL ANALYTICS",730,F(19,True),MUTED,W);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
