"""Distinct Telegram result-card identities for GOOL CORE, HT HUNTER and LATE RISK.
Visual contract selected for the bot:
CORE = gold + cool orange cat; HT = electric blue + shocked cat;
LATE RISK = red + angry/screaming cat.  The mascot is drawn at runtime so every
subscriber receives the same generated card without depending on a local asset.
"""
from __future__ import annotations
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
import requests,re
from live_engine import _feed

W,H=1080,1120
BG=(5,9,16);PANEL=(11,18,30);TEXT=(246,248,252);MUTED=(160,173,195);GREEN=(83,220,124)
GOLD=(246,181,48);BLUE=(42,158,255);RED=(255,61,67)

def _font(size,bold=False):
    for p in (("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf")):
        try:return ImageFont.truetype(p,size)
        except OSError:pass
    return ImageFont.load_default()
def _center(d,t,y,f,c):
    b=d.textbbox((0,0),t,font=f);d.text(((W-(b[2]-b[0]))/2,y),t,font=f,fill=c)
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
def _cat(d,kind,accent):
    """Compact meme-cat mascot: sunglasses / shocked / angry."""
    x,y=150,160
    fur=(224,150,70) if kind=="core" else ((205,210,216) if kind=="ht" else (215,205,190))
    # ears + head
    d.polygon([(75,105),(100,25),(145,100)],fill=fur,outline=accent);d.polygon([(155,100),(205,25),(225,110)],fill=fur,outline=accent)
    d.ellipse((70,75,230,235),fill=fur,outline=accent,width=4)
    if kind=="core":
        d.rounded_rectangle((83,112,145,145),10,fill=(5,5,5),outline=accent,width=2);d.rounded_rectangle((155,112,217,145),10,fill=(5,5,5),outline=accent,width=2);d.line((145,125,155,125),fill=accent,width=4)
        d.ellipse((135,150,165,176),fill=(80,45,30));d.pieslice((125,168,175,225),0,180,fill=(20,10,10));d.text((54,242),"GOOOL!",font=_font(31,True),fill=accent)
    elif kind=="ht":
        d.ellipse((92,105,135,160),fill=(255,255,255),outline=accent,width=3);d.ellipse((165,105,208,160),fill=(255,255,255),outline=accent,width=3);d.ellipse((108,123,125,148),fill=(5,5,5));d.ellipse((181,123,198,148),fill=(5,5,5));d.ellipse((128,165,174,222),fill=(25,10,15),outline=accent,width=3);d.text((52,242),"GOOOL?!",font=_font(29,True),fill=accent)
    else:
        d.line((91,112,135,128),fill=(30,20,20),width=7);d.line((166,128,210,112),fill=(30,20,20),width=7);d.ellipse((100,128,130,158),fill=(255,255,255));d.ellipse((174,128,204,158),fill=(255,255,255));d.ellipse((135,166,171,225),fill=(35,5,8),outline=accent,width=3);d.text((45,242),"GOOOOL!!",font=_font(28,True),fill=accent)

def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
    delta=delta or {};kind="core" if engine in {"core","main","primary"} else "ht" if engine in {"first_half","ht_hunter","ht"} else "risk"
    accent=GOLD if kind=="core" else BLUE if kind=="ht" else RED
    title="GOOL CORE" if kind=="core" else "GOOL HT HUNTER" if kind=="ht" else "GOOL LATE RISK"
    subtitle="ГЛАВНЫЙ СИГНАЛ" if kind=="core" else "ГОЛ ДО ПЕРЕРЫВА" if kind=="ht" else "ПОЗДНИЙ ГОЛ"
    img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img)
    for e,a in ((16,.16),(10,.28),(5,.48)):d.rounded_rectangle((25-e,20-e,W-25+e,H-25+e),34+e,outline=tuple(int(c*a) for c in accent),width=3)
    d.rounded_rectangle((25,20,W-25,H-25),34,outline=accent,width=3)
    _cat(d,kind,accent);d.text((300,60),title,font=_font(47,True),fill=accent);d.text((303,112),subtitle,font=_font(25,True),fill=TEXT)
    status="SIGNAL WON" if result=="win" else "SIGNAL LOST" if result=="loss" else "LIVE SIGNAL";sf=_font(22,True);sb=d.textbbox((0,0),status,font=sf);d.rounded_rectangle((W-310,75,W-65,124),15,fill=(17,25,39),outline=accent,width=2);d.text((W-187-(sb[2]-sb[0])/2,87),status,font=sf,fill=accent)
    hn,an=_logos(getattr(match,"event_id",""));_badge(img,d,175,390,_download(hn),match.home,accent);_badge(img,d,W-175,390,_download(an),match.away,accent)
    _glow_box(d,(380,305,700,475),accent,28);_center(d,f"{match.home_score} : {match.away_score}",343,_font(67,True),TEXT);_center(d,f"{match.minute}'",418,_font(30,True),accent)
    hf=_fit(d,match.home,320);af=_fit(d,match.away,320);hb=d.textbbox((0,0),match.home,font=hf);ab=d.textbbox((0,0),match.away,font=af);d.text((175-(hb[2]-hb[0])/2,490),match.home,font=hf,fill=TEXT);d.text((W-175-(ab[2]-ab[0])/2,490),match.away,font=af,fill=TEXT);_center(d,getattr(match,"league","") or "LIVE FOOTBALL",545,_font(21),MUTED)
    headline="ЗАХОД!" if result=="win" else "НЕ ЗАШЁЛ" if result=="loss" else "СИГНАЛ НА ГОЛ";_center(d,headline,595,_font(48,True),accent)
    _glow_box(d,(80,670,1000,875),accent);d.text((130,705),"✓ ГОЛ ПОДТВЕРЖДЁН" if result=="win" else "СИГНАЛ АКТИВЕН" if not result else "СИГНАЛ ЗАКРЫТ",font=_font(34,True),fill=accent);d.line((130,755,920,755),fill=tuple(int(c*.55) for c in accent),width=2);d.text((130,785),"Сигнал успешно отработал" if result=="win" else "Один сигнал → один результат" if kind!="core" else "GOOL AI продолжает анализ матча",font=_font(27),fill=TEXT)
    if result is None:
        d.text((130,830),f"Рейтинг {int(round(score))}/100",font=_font(24,True),fill=TEXT)
        if odd and float(odd)>1:d.text((700,830),f"LIVE {float(odd):.2f}",font=_font(24,True),fill=accent)
    _center(d,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",990,_font(23,True),MUTED);_center(d,"ЗОЛОТО • ПЕРВЫЙ ТАЙМ • ВТОРОЙ ТАЙМ",1040,_font(18,True),accent)
    out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
