from __future__ import annotations
from io import BytesIO
import re,requests,textwrap
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from live_engine import _feed
BLUE=(45,166,255);PURPLE=(190,75,255);WHITE=(247,249,252);MUTED=(157,171,193);GREEN=(83,220,116);RED=(244,64,64);BG=(4,9,17);PANEL=(10,18,31);LINE=(47,63,86)
def F(size,bold=False):
 for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
  try:return ImageFont.truetype(p,size)
  except:pass
 return ImageFont.load_default()
def fields(rec):
 out={}
 for t in str(rec or '').split('¬'):
  if '÷' in t:k,v=t.split('÷',1);out.setdefault(k,v)
 return out
def logos(eid):
 try:body=_feed('f_1_0_0_en_1') or ''
 except:return '',''
 for c in body.split('~'):
  if f'AA÷{eid}¬' in c:
   f=fields(c);return f.get('OA',''),f.get('OB','')
 return '',''
def dl(name):
 if not name:return None
 try:
  r=requests.get(f'https://static.flashscore.com/res/image/data/{name}',timeout=5,headers={'User-Agent':'Mozilla/5.0'})
  if r.ok:return Image.open(BytesIO(r.content)).convert('RGBA')
 except:pass
 return None
def fit(draw,text,maxw,size=42,bold=True):
 for s in range(size,17,-2):
  ft=F(s,bold)
  if draw.textbbox((0,0),str(text),font=ft)[2]<=maxw:return ft
 return F(18,bold)
def center(draw,text,y,font,fill,w):
 b=draw.textbbox((0,0),str(text),font=font);draw.text(((w-(b[2]-b[0]))/2,y),str(text),font=font,fill=fill)
def panel(base,box,accent,radius=28,width=3):
 glow=Image.new('RGBA',base.size,(0,0,0,0));g=ImageDraw.Draw(glow)
 for e,a in [(12,42),(7,72),(3,118)]:g.rounded_rectangle((box[0]-e,box[1]-e,box[2]+e,box[3]+e),radius+e,outline=accent+(a,),width=3)
 base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)));ImageDraw.Draw(base).rounded_rectangle(box,radius,fill=PANEL+(255,),outline=accent,width=width)
def crest(base,im,cx,cy,accent,size=160):
 d=ImageDraw.Draw(base);r=size//2;d.ellipse((cx-r-8,cy-r-8,cx+r+8,cy+r+8),outline=accent,width=3);d.ellipse((cx-r,cy-r,cx+r,cy+r),fill=(12,23,38),outline=accent,width=2)
 if im:
  bb=im.getbbox();im=im.crop(bb) if bb else im;s=min((size-20)/max(1,im.width),(size-20)/max(1,im.height));im=im.resize((max(1,int(im.width*s)),max(1,int(im.height*s))),Image.Resampling.LANCZOS);base.alpha_composite(im,(cx-im.width//2,cy-im.height//2))
def _val(delta,key,fmt='int'):
 v=delta.get(key)
 if v is None:return '—'
 try:return f'{float(v):.2f}' if fmt=='float' else f'{int(round(float(v)))}'
 except:return '—'
def _num(delta,key):
 try:return float(delta.get(key) or 0)
 except:return 0.0
def _box(d,xy,title,value,accent=WHITE):
 d.rounded_rectangle(xy,16,fill=(9,18,31),outline=LINE,width=1);x1,y1,x2,y2=xy;d.text((x1+16,y1+13),title,font=F(16,True),fill=MUTED);d.text((x1+16,y1+44),value,font=fit(d,value,x2-x1-32,26,True),fill=accent)
def _header_text(engine):
 if engine=='first_half_goal':return PURPLE,'GOOL 2.0 • FIRST HALF GOAL','АНАЛИЗ ГОЛА ДО ПЕРЕРЫВА','1T'
 return BLUE,'GOOL 2.0 • SECOND HALF','АНАЛИЗ ДВУХ ГОЛОВ ПОСЛЕ ПЕРЕРЫВА','2T'
def _signal_label(engine):return 'ОЖИДАЕМ ГОЛ ДО ПЕРЕРЫВА' if engine=='first_half_goal' else 'ОЖИДАЕМ 2+ ГОЛА ВО 2-М ТАЙМЕ'
def _why(engine,score,delta,timing):
 xg=_num(delta,'xg');xgot=_num(delta,'xgot');shots=_num(delta,'shots');sot=_num(delta,'shots_on_target');bc=_num(delta,'big_chances');box=_num(delta,'shots_inside_box');parts=[]
 if xg>=1.2:parts.append(f'xG {xg:.2f} показывает качественные моменты')
 if xgot>=.8:parts.append(f'xGoT {xgot:.2f} подтверждает опасность ударов')
 if sot>=4:parts.append(f'{int(sot)} ударов в створ')
 elif shots>=10:parts.append(f'{int(shots)} ударов поддерживают высокий темп')
 if bc>=2:parts.append(f'{int(bc)} больших момента')
 if box>=7:parts.append(f'{int(box)} ударов/действий в штрафной')
 try:
  pct=float(timing.get('pct'))
  if pct>=55:parts.append(f'лига поддерживает сценарий: {pct:.0f}%')
 except:pass
 if engine=='first_half_goal':prefix='GOOL отслеживал динамику с начала матча и дал сигнал в окне 15–25′.'
 else:prefix='GOOL использовал полный первый тайм и принял решение только в перерыве.'
 if not parts:parts.append(f'совокупный рейтинг стратегии {float(score):.0f}/100 прошёл аналитический порог')
 return prefix+' '+'; '.join(parts[:4])+'.'
def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
 delta=delta or {};timing=delta.get('_timing') or {};accent,title,subtitle,mode=_header_text(engine)
 if result is not None:return render_result_card(match,engine,result)
 W,H=1200,1230;img=Image.new('RGBA',(W,H),BG+(255,));d=ImageDraw.Draw(img);panel(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img)
 d.text((55,40),title,font=F(38,True),fill=WHITE);d.text((57,88),subtitle,font=F(23,True),fill=accent);d.rounded_rectangle((900,43,1145,105),17,outline=accent,width=2);d.text((930,59),mode,font=fit(d,mode,190,21,True),fill=accent)
 hn,an=logos(getattr(match,'event_id',''));crest(img,dl(hn),195,292,accent);crest(img,dl(an),1005,292,accent);panel(img,(430,205,770,388),accent,28,2);d=ImageDraw.Draw(img);center(d,f'{match.home_score} : {match.away_score}',246,F(70,True),WHITE,W);center(d,'ПЕРЕРЫВ' if getattr(match,'is_halftime',False) else f"{match.minute}'",331,F(31,True),accent,W)
 for x,n in ((195,match.home),(1005,match.away)):
  f=fit(d,n,340,32);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,407),n,font=f,fill=WHITE)
 center(d,getattr(match,'league','') or 'LIVE FOOTBALL',458,F(21),MUTED,W)
 panel(img,(55,510,1145,700),accent,22,2);d=ImageDraw.Draw(img);d.text((90,538),'АНАЛИТИЧЕСКИЙ СИГНАЛ',font=F(20,True),fill=MUTED);label=_signal_label(engine);d.text((90,582),label,font=fit(d,label,690,33,True),fill=WHITE);d.text((90,638),'Коэффициенты не участвуют в решении',font=F(19,True),fill=MUTED);d.text((835,545),'GOOL',font=F(17,True),fill=MUTED);d.text((815,584),f'{int(round(score))}/100',font=F(46,True),fill=accent)
 labels=[('xG',_val(delta,'xg','float')),('xGoT',_val(delta,'xgot','float')),('УДАРЫ',_val(delta,'shots')),('В СТВОР',_val(delta,'shots_on_target')),('BIG CHANCES',_val(delta,'big_chances')),('В ШТРАФНОЙ',_val(delta,'shots_inside_box'))];y=742;gap=12;cw=(1090-gap*2)/3
 for i,(lab,val) in enumerate(labels):row=i//3;col=i%3;xa=55+col*(cw+gap);ya=y+row*98;_box(d,(xa,ya,xa+cw,ya+82),lab,val,WHITE)
 d.rounded_rectangle((55,955,1145,1158),22,fill=(9,18,31),outline=LINE,width=1);d.text((82,978),'ПОЧЕМУ GOOL ДАЛ СИГНАЛ',font=F(21,True),fill=accent);yy=1017
 for line in textwrap.wrap(_why(engine,score,delta,timing),width=92)[:5]:d.text((82,yy),line,font=F(17),fill=WHITE);yy+=27
 center(d,'FLASHScore • LIVE STATS • xG/xGoT • FORM/H2H • MULTI-SOURCE ANALYTICS',1178,F(16,True),MUTED,W);out=BytesIO();img.convert('RGB').save(out,'PNG',optimize=True);return out.getvalue()
def render_result_card(match,engine,result,market=None,odd=None):
 accent,title,_,mode=_header_text(engine);W,H=1200,800;img=Image.new('RGBA',(W,H),BG+(255,));d=ImageDraw.Draw(img);panel(img,(24,20,W-24,H-22),accent,32,3);d=ImageDraw.Draw(img);d.text((55,42),title,font=F(34,True),fill=WHITE);d.rounded_rectangle((1000,40,1140,95),15,outline=accent,width=2);d.text((1035,54),mode,font=F(20,True),fill=accent);is_win=str(result).lower()=='win';headline='СИГНАЛ ПОДТВЕРЖДЁН' if is_win else 'СИГНАЛ НЕ ПОДТВЕРЖДЁН';center(d,headline,120,fit(d,headline,1000,52,True),GREEN if is_win else RED,W);hn,an=logos(getattr(match,'event_id',''));crest(img,dl(hn),190,380,accent,165);crest(img,dl(an),1010,380,accent,165);panel(img,(425,287,775,472),accent,28,2);d=ImageDraw.Draw(img);center(d,f'{match.home_score} : {match.away_score}',325,F(72,True),WHITE,W);center(d,'HT' if engine=='first_half_goal' else 'FT',408,F(30,True),accent,W);center(d,_signal_label(engine),545,fit(d,_signal_label(engine),950,30,True),WHITE,W);center(d,'Результат относится к футбольному прогнозу, не к коэффициенту',620,F(21),MUTED,W);center(d,'GOOL AI 2.0 • STRATEGY ANALYTICS',735,F(19,True),MUTED,W);out=BytesIO();img.convert('RGB').save(out,'PNG',optimize=True);return out.getvalue()
