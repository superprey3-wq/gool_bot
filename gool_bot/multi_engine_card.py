from __future__ import annotations
from io import BytesIO
import re,requests,textwrap
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from live_engine import _feed
GOLD=(246,181,48);BLUE=(40,158,255);PURPLE=(171,105,255);WHITE=(246,248,252);MUTED=(157,170,192);GREEN=(82,220,116);BG=(4,9,17);PANEL=(10,18,31);LINE=(53,70,94)
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
 for c in body.split("~"):
  if f"AA÷{eid}¬" in c:
   f=fields(c);return f.get("OA",""),f.get("OB","")
 return "",""
def dl(name):
 if not name:return None
 try:
  r=requests.get(f"https://static.flashscore.com/res/image/data/{name}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
  if r.ok:return Image.open(BytesIO(r.content)).convert("RGBA")
 except:pass
 return None
def fit(d,t,w,size=42,bold=True):
 for s in range(size,16,-2):
  f=F(s,bold)
  if d.textbbox((0,0),str(t),font=f)[2]<=w:return f
 return F(17,bold)
def center(d,t,y,f,c,w):
 b=d.textbbox((0,0),str(t),font=f);d.text(((w-(b[2]-b[0]))/2,y),str(t),font=f,fill=c)
def glow(base,box,a,r=28,width=3):
 layer=Image.new("RGBA",base.size,(0,0,0,0));g=ImageDraw.Draw(layer)
 for e,alpha in ((10,40),(5,70)):g.rounded_rectangle((box[0]-e,box[1]-e,box[2]+e,box[3]+e),r+e,outline=a+(alpha,),width=3)
 base.alpha_composite(layer.filter(ImageFilter.GaussianBlur(5)));ImageDraw.Draw(base).rounded_rectangle(box,r,fill=PANEL+(255,),outline=a,width=width)
def crest(base,im,cx,cy,a):
 d=ImageDraw.Draw(base);r=78;d.ellipse((cx-r-7,cy-r-7,cx+r+7,cy+r+7),outline=a,width=3);d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(12,23,38),outline=LINE,width=2)
 if im:
  bb=im.getbbox();im=im.crop(bb) if bb else im;s=min(135/max(1,im.width),135/max(1,im.height));im=im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS);base.alpha_composite(im,(cx-im.width//2,cy-im.height//2))
def info(engine):
 if engine=="first_half_goal":return BLUE,"GOOL • 1-Й ТАЙМ","ГОЛ ДО ПЕРЕРЫВА","15–25'","Динамический тотал 1-го тайма"
 if engine=="second_half_over15":return PURPLE,"GOOL • 2-Й ТАЙМ","ДВА ГОЛА ПОСЛЕ ПЕРЕРЫВА","HT","ТБ1.5 во 2-м тайме"
 return GOLD,"GOOL CORE","LIVE MARKET SELECTION","LIVE","Лучший рынок матча"
def val(d,k,floatv=False):
 try:return f"{float(d[k]):.2f}" if floatv else str(int(round(float(d[k]))))
 except:return "—"
def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
 delta=delta or {};timing=delta.get("_timing") or {};a,title,subtitle,window,market=info(engine)
 if result:return render_result_card(match,engine,result)
 W,H=1200,1240;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow(img,(24,20,W-24,H-22),a,32,3);d=ImageDraw.Draw(img)
 d.text((55,42),title,font=F(37,True),fill=a);d.text((57,88),subtitle,font=F(23,True),fill=WHITE);d.rounded_rectangle((940,45,1145,102),16,outline=a,width=2);d.text((973,61),"ENTRY",font=F(23,True),fill=a)
 hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),190,292,a);crest(img,dl(an),1010,292,a);glow(img,(430,205,770,385),a,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",247,F(68,True),WHITE,W);center(d,"ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'",330,F(30,True),a,W)
 for x,n in ((190,match.home),(1010,match.away)):
  f=fit(d,n,345,31);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,405),n,font=f,fill=WHITE)
 center(d,getattr(match,"league","") or "LIVE FOOTBALL",458,F(21),MUTED,W)
 glow(img,(55,505,1145,690),a,22,2);d=ImageDraw.Draw(img);d.text((88,532),"⭐ СТАВКА СТРАТЕГИИ",font=F(22,True),fill=a);d.text((88,572),market,font=fit(d,market,720,34,True),fill=WHITE);d.text((88,620),f"КЭФФИЦИЕНТ  {float(odd):.2f}" if odd and float(odd)>1 else "КОЭФФИЦИЕНТ НЕ ПОДТВЕРЖДЁН",font=F(23,True),fill=GREEN if odd and float(odd)>1 else MUTED);d.line((860,530,860,665),fill=LINE,width=2);d.text((900,535),"SCORE",font=F(17,True),fill=MUTED);d.text((900,568),f"{int(round(score))}/100",font=F(40,True),fill=a);d.text((900,625),f"ОКНО {window}",font=F(18,True),fill=MUTED)
 labels=[("xG",val(delta,"xg",True)),("xGoT",val(delta,"xgot",True)),("УДАРЫ",val(delta,"shots")),("В СТВОР",val(delta,"shots_on_target")),("BIG CHANCES",val(delta,"big_chances")),("В ШТРАФНОЙ",val(delta,"shots_inside_box"))];y=730;cw=350
 for i,(lab,v) in enumerate(labels):
  row,col=divmod(i,3);x=55+col*365;yy=y+row*105;d.rounded_rectangle((x,yy,x+cw,yy+88),16,fill=(8,17,30),outline=LINE,width=1);d.text((x+17,yy+13),lab,font=F(16,True),fill=MUTED);d.text((x+17,yy+43),v,font=F(27,True),fill=WHITE)
 d.rounded_rectangle((55,955,1145,1142),20,fill=(8,17,30),outline=a,width=2);d.text((82,980),"ПОЧЕМУ ВХОД",font=F(21,True),fill=a)
 if engine=="first_half_goal":why="GOOL наблюдает матч с 0'. К 15–25 минуте накопленный темп, качество моментов и LIVE-рынок должны одновременно подтверждать следующий гол до перерыва."
 else:why="Решение принимается только в перерыве. Весь первый тайм используется как выборка для оценки двух голов во втором: xG/xGoT, створы, big chances, штрафная и профиль лиги."
 if timing.get("pct") is not None:why+=f" Исторический профиль лиги для этого временного сегмента: {float(timing['pct']):.0f}%."
 yy=1023
 for line in textwrap.wrap(why,width=83)[:4]:d.text((82,yy),line,font=F(19),fill=WHITE);yy+=29
 center(d,"GOOL AI • STRATEGY ENTRY",1182,F(18,True),MUTED,W);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
def render_result_card(match,engine,result):
 a,title,subtitle,_,market=info(engine);W,H=1200,800;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);glow(img,(24,20,W-24,H-22),a,32,3);d=ImageDraw.Draw(img);d.text((55,42),title,font=F(34,True),fill=a);center(d,"✓ ЗАШЛО" if result=="win" else "✕ НЕ ЗАШЛО",125,F(65,True),GREEN if result=="win" else a,W);hn,an=logos(getattr(match,"event_id",""));crest(img,dl(hn),190,370,a);crest(img,dl(an),1010,370,a);glow(img,(425,275,775,455),a,28,2);d=ImageDraw.Draw(img);center(d,f"{match.home_score} : {match.away_score}",315,F(70,True),WHITE,W);center(d,f"{match.minute}'",395,F(30,True),a,W);center(d,market,565,F(26,True),WHITE,W);center(d,"GOOL AI • STRATEGY RESULT",735,F(18,True),MUTED,W);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
