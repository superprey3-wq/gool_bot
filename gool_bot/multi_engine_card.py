"""Distinct Telegram cards for GOOL HT HUNTER and LATE RISK."""
from __future__ import annotations
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
import requests,re
from live_engine import _feed

W,H=1080,1120
BG=(5,9,16);PANEL=(11,18,30);TEXT=(246,248,252);MUTED=(160,173,195);GREEN=(83,220,124)
BLUE=(42,158,255);RED=(255,61,67)

def _font(size,bold=False):
    for p in (("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")):
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default()
def _center(d,t,y,f,c):
    b=d.textbbox((0,0),t,font=f);d.text(((W-b[2]+b[0])/2,y),t,font=f,fill=c)
def _fields(record):
    out={}
    for token in record.split("¬"):
        if "÷" in token:k,v=token.split("÷",1);out.setdefault(k,v)
    return out
def _logos(eid):
    try:body=_feed("f_1_0_0_en_1") or ""
    except Exception:return "",""
    needle=f"AA÷{eid}¬"
    for chunk in body.split("~"):
        if needle in chunk:
            f=_fields(chunk);return f.get("OA",""),f.get("OB","")
    return "",""
def _download(name):
    if not name:return None
    try:
        r=requests.get(f"https://static.flashscore.com/res/image/data/{name}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
        if r.ok:
            im=Image.open(BytesIO(r.content)).convert("RGBA");im.thumbnail((120,120),Image.Resampling.LANCZOS);return im
    except Exception:pass
    return None
def _badge(img,d,x,y,logo,name,accent):
    for e,a in ((12,.25),(7,.45),(3,.75)):d.ellipse((x-66-e,y-66-e,x+66+e,y+66+e),outline=tuple(int(c*a) for c in accent),width=3)
    d.ellipse((x-66,y-66,x+66,y+66),fill=(18,29,46),outline=accent,width=3)
    if logo:
        bb=logo.getbbox();logo=logo.crop(bb) if bb else logo;scale=min(112/max(1,logo.width),112/max(1,logo.height));logo=logo.resize((max(1,int(logo.width*scale)),max(1,int(logo.height*scale))),Image.Resampling.LANCZOS);img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
    else:
        initials="".join(x[0] for x in re.findall(r"[A-Za-zА-Яа-я0-9]+",name)[:2]).upper() or "?";f=_font(32,True);b=d.textbbox((0,0),initials,font=f);d.text((x-(b[2]-b[0])/2,y-20),initials,font=f,fill=TEXT)
def _fit(d,text,width,size=32):
    for s in range(size,17,-2):
        f=_font(s,True)
        if d.textbbox((0,0),str(text),font=f)[2]<=width:return f
    return _font(18,True)
def _glow_box(d,box,accent,r=24):
    x1,y1,x2,y2=box
    for e,a in ((9,.20),(5,.35),(2,.60)):d.rounded_rectangle((x1-e,y1-e,x2+e,y2+e),r+e,outline=tuple(int(c*a) for c in accent),width=2)
    d.rounded_rectangle(box,r,fill=PANEL,outline=accent,width=2)
def _pair(stats,key):
    try:a,b=stats.get(key,(0,0));return float(a or 0)+float(b or 0)
    except Exception:return 0.0
def render_engine_card(match,engine,score,delta,odd=None,result=None):
    is_ht=engine=="first_half";accent=BLUE if is_ht else RED;title="GOOL HT HUNTER" if is_ht else "GOOL LATE RISK";subtitle="ГОЛ ДО ПЕРЕРЫВА" if is_ht else "ПОЗДНИЙ ГОЛ";img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img)
    # outer neon frame
    for e,a in ((16,.16),(10,.28),(5,.48)):d.rounded_rectangle((25-e,20-e,W-25+e,H-25+e),34+e,outline=tuple(int(c*a) for c in accent),width=3)
    d.rounded_rectangle((25,20,W-25,H-25),34,outline=accent,width=3)
    d.text((70,60),"⏱" if is_ht else "⚠",font=_font(50,True),fill=accent);d.text((145,58),title,font=_font(47,True),fill=accent);d.text((148,112),subtitle,font=_font(25,True),fill=TEXT)
    status="SIGNAL WON" if result=="win" else "SIGNAL LOST" if result=="loss" else "FIRST HALF SIGNAL" if is_ht else "SECOND HALF RISK";sf=_font(22,True);sb=d.textbbox((0,0),status,font=sf);d.rounded_rectangle((W-310,75,W-65,124),15,fill=(17,25,39),outline=GREEN if result=="win" else accent,width=2);d.text((W-187-(sb[2]-sb[0])/2,87),status,font=sf,fill=GREEN if result=="win" else accent)
    hn,an=_logos(getattr(match,"event_id",""));_badge(img,d,175,305,_download(hn),match.home,accent);_badge(img,d,W-175,305,_download(an),match.away,accent)
    _glow_box(d,(380,220,700,390),accent,28);_center(d,f"{match.home_score} : {match.away_score}",258,_font(67,True),TEXT);_center(d,f"{match.minute}'",333,_font(30,True),accent)
    hf=_fit(d,match.home,320);af=_fit(d,match.away,320);hb=d.textbbox((0,0),match.home,font=hf);ab=d.textbbox((0,0),match.away,font=af);d.text((175-(hb[2]-hb[0])/2,405),match.home,font=hf,fill=TEXT);d.text((W-175-(ab[2]-ab[0])/2,405),match.away,font=af,fill=TEXT);_center(d,getattr(match,"league","") or "LIVE FOOTBALL",458,_font(21),MUTED)
    headline="✅ ЗАШЁЛ!" if result=="win" else "❌ НЕ ЗАШЁЛ" if result=="loss" else "🔥 СИГНАЛ НА ГОЛ";_center(d,headline,510,_font(43,True),GREEN if result=="win" else accent)
    _glow_box(d,(65,575,420,750),accent);d.text((100,605),"HT SCORE" if is_ht else "RISK SCORE",font=_font(23,True),fill=MUTED);d.text((100,645),f"{int(round(score))}/100",font=_font(54,True),fill=accent);d.text((100,708),"ОДНОРАЗОВЫЙ СИГНАЛ",font=_font(17,True),fill=TEXT)
    _glow_box(d,(450,575,1015,750),accent);d.text((485,605),"ДИНАМИКА ПОСЛЕДНИХ 10 МИНУТ",font=_font(21,True),fill=TEXT)
    vals=[("xG",float(delta.get("xg",0))),("УДАРЫ",float(delta.get("shots",0))),("В СТВОР",float(delta.get("shots_on_target",0))),("BIG CHANCES",float(delta.get("big_chances",0)))]
    x=485
    for label,val in vals:
        d.text((x,652),label,font=_font(16,True),fill=MUTED);txt=f"+{val:.2f}" if label=="xG" else f"+{int(val)}";d.text((x,686),txt,font=_font(30,True),fill=GREEN);x+=132
    _glow_box(d,(65,785,1015,970),accent);d.text((100,815),"ПОЧЕМУ СИГНАЛ",font=_font(23,True),fill=accent)
    pressure="РЕЗКО РАСТЁТ" if score>=85 else "РАСТЁТ";d.text((100,858),f"⚡ Давление: {pressure}",font=_font(25,True),fill=TEXT);d.text((100,900),f"🎯 Касания в штрафной +{int(float(delta.get('touches_box',0)))}  •  Угловые +{int(float(delta.get('corners',0)))}",font=_font(22),fill=TEXT)
    if odd and float(odd)>1:d.text((700,858),f"КЭФ НА ГОЛ  {float(odd):.2f}",font=_font(28,True),fill=accent)
    _center(d,"ОДИН СИГНАЛ  →  ОДИН РЕЗУЛЬТАТ",1015,_font(23,True),accent);_center(d,"GOOL AI  •  MULTI-ENGINE LIVE ANALYTICS",1060,_font(18,True),MUTED)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
