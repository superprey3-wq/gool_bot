from __future__ import annotations
from io import BytesIO
import requests
from PIL import Image,ImageDraw,ImageFont,ImageFilter
from live_engine import _feed
GOLD=(255,188,42);BLUE=(25,154,255);RED=(255,48,60);WHITE=(248,250,255);MUTED=(165,177,198);BG=(3,7,14)
CATS={'core':'https://www.meme-arsenal.com/memes/6c1fa93dc90aef18cb6575813e808033.jpg','ht':'https://kartinkof.club/uploads/posts/2022-03/1648297537_10-kartinkof-club-p-mem-kot-v-shoke-11.png','risk':'https://upload.wikimedia.org/wikipedia/commons/3/33/Hannibal_Poenaru_-_Nasty_cat_%21_%28by-sa%29.jpg'}
def F(s,b=False):
 for p in ((f'/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if b else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),(f'/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if b else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf')):
  try:return ImageFont.truetype(p,s)
  except:pass
 return ImageFont.load_default()
def center(d,t,y,f,c,w):
 b=d.textbbox((0,0),str(t),font=f);d.text(((w-(b[2]-b[0]))/2,y),str(t),font=f,fill=c)
def fit(d,t,w,s=30,b=True):
 for z in range(s,12,-2):
  f=F(z,b)
  if d.textbbox((0,0),str(t),font=f)[2]<=w:return f
 return F(12,b)
def fields(r):
 o={}
 for x in r.split('¬'):
  if '÷' in x:k,v=x.split('÷',1);o.setdefault(k,v)
 return o
def logos(eid):
 try:body=_feed('f_1_0_0_en_1') or ''
 except:return '',''
 for c in body.split('~'):
  if f'AA÷{eid}¬' in c:
   f=fields(c);return f.get('OA',''),f.get('OB','')
 return '',''
def dl(url,n=150):
 if not url:return None
 try:
  r=requests.get(url,timeout=6,headers={'User-Agent':'Mozilla/5.0'})
  if r.ok:
   im=Image.open(BytesIO(r.content)).convert('RGBA');im.thumbnail((n,n),Image.Resampling.LANCZOS);return im
 except:pass
 return None
def logo(n,s=125):return dl(f'https://static.flashscore.com/res/image/data/{n}',s) if n else None
def glow(img,box,a,r=24):
 g=Image.new('RGBA',img.size,(0,0,0,0));d=ImageDraw.Draw(g)
 for e,al in ((16,55),(10,90),(5,150)):d.rounded_rectangle((box[0]-e,box[1]-e,box[2]+e,box[3]+e),r+e,outline=a+(al,),width=3)
 img.alpha_composite(g.filter(ImageFilter.GaussianBlur(7)));ImageDraw.Draw(img).rounded_rectangle(box,r,fill=(7,12,22,246),outline=a,width=3)
def frame(img,a):
 w,h=img.size;g=Image.new('RGBA',img.size,(0,0,0,0));d=ImageDraw.Draw(g)
 for i,al in ((14,45),(24,80),(34,140)):d.rounded_rectangle((i,i,w-i,h-i),42,outline=a+(al,),width=4)
 img.alpha_composite(g.filter(ImageFilter.GaussianBlur(8)));ImageDraw.Draw(img).rounded_rectangle((32,28,w-32,h-28),40,outline=a,width=4)
def paste(img,im,x,y):
 if im:img.alpha_composite(im,(int(x-im.width/2),int(y-im.height/2)))
def kind(e):return 'core' if e in {'core','main','primary'} else 'ht' if e in {'first_half','ht_hunter','ht'} else 'risk'
def accent(k):return GOLD if k=='core' else BLUE if k=='ht' else RED
def sig(m,k,score,delta,odd):
 W,H=1080,1450;a=accent(k);im=Image.new('RGBA',(W,H),BG+(255,));frame(im,a);d=ImageDraw.Draw(im)
 title='GOOL CORE' if k=='core' else 'GOOL HT HUNTER' if k=='ht' else 'GOOL LATE RISK';sub='ГЛАВНЫЙ СИГНАЛ' if k=='core' else 'ГОЛ ДО ПЕРЕРЫВА' if k=='ht' else 'ПОЗДНИЙ ГОЛ';icon='♛' if k=='core' else '⚽' if k=='ht' else '🔥'
 center(d,icon,42,F(72,True),a,W);center(d,title,135,F(66,True),WHITE,W);center(d,sub,215,F(28,True),a,W)
 glow(im,(310,270,770,330),a);center(d,'MASTER SIGNAL' if k=='core' else 'FIRST HALF SIGNAL' if k=='ht' else 'SECOND HALF RISK',283,F(24,True),WHITE,W)
 center(d,'⚽  '+(getattr(m,'league','') or 'LIVE FOOTBALL'),360,fit(d,getattr(m,'league',''),760,24,False),MUTED,W)
 glow(im,(85,410,995,590),a);hn,an=logos(getattr(m,'event_id',''));paste(im,logo(hn),185,495);paste(im,logo(an),895,495)
 center(d,f"{m.home_score} : {m.away_score}",442,F(70,True),WHITE,W);hf=fit(d,m.home,250,30);af=fit(d,m.away,250,30);hb=d.textbbox((0,0),m.home,font=hf);ab=d.textbbox((0,0),m.away,font=af);d.text((185-(hb[2]-hb[0])/2,555),m.home,font=hf,fill=WHITE);d.text((895-(ab[2]-ab[0])/2,555),m.away,font=af,fill=WHITE)
 glow(im,(430,545,650,630),a);center(d,f"{m.minute}'",560,F(46,True),a,W)
 glow(im,(120,675,960,805),a);center(d,'🔥  СИГНАЛ НА ГОЛ',700,F(48,True),WHITE,W);center(d,'ДО КОНЦА 1-ГО ТАЙМА' if k=='ht' else 'ПОЗДНИЙ ГОЛ' if k=='risk' else 'ОСНОВНОЙ ДВИЖОК',758,F(24,True),a,W)
 glow(im,(315,840,765,985),a);center(d,'MASTER' if k=='core' else 'HT SCORE' if k=='ht' else 'RISK SCORE',860,F(26,True),MUTED,W);center(d,f'{int(round(float(score or 0)))}/100',902,F(58,True),a,W)
 xs=[70,305,540,775,1010];vals=[('xG',str(delta.get('xg_total','—'))) if k=='core' else ("xG (10')",f"+{float(delta.get('xg',0)):.2f}"),('Удары',str(delta.get('shots_pair','—'))) if k=='core' else ('Удары',f"+{int(float(delta.get('shots',0)))}"),('В створ',str(delta.get('sot_pair','—'))) if k=='core' else ('В створ',f"+{int(float(delta.get('shots_on_target',0)))}"),('LIVE кэф',f'{float(odd):.2f}' if odd else '—')]
 for i,(lab,val) in enumerate(vals):
  b=(xs[i]+10,1025,xs[i+1]-10,1155);glow(im,b,a,18);cx=(b[0]+b[2])//2;lf=fit(d,lab,185,19,False);vf=fit(d,val,185,34);lb=d.textbbox((0,0),lab,font=lf);vb=d.textbbox((0,0),val,font=vf);d.text((cx-(lb[2]-lb[0])/2,1048),lab,font=lf,fill=MUTED);d.text((cx-(vb[2]-vb[0])/2,1090),val,font=vf,fill=a)
 glow(im,(75,1200,1005,1370),a);reasons=['Сильное давление на ворота','Матч сохраняет атакующий темп','Высокая вероятность ещё одного гола'] if k=='core' else ['Явное усиление атаки перед перерывом','Свежий тренд последних 10 минут','Один сигнал → один результат'] if k=='ht' else ['Сильный навал в концовке матча','Интенсивность продолжает расти','Один сигнал → один результат']
 for i,t in enumerate(reasons):d.text((120,1230+i*43),'⚡' if i==0 else '●',font=F(23,True),fill=a);d.text((170,1230+i*43),t,font=fit(d,t,760,23,False),fill=WHITE)
 o=BytesIO();im.convert('RGB').save(o,'PNG',optimize=True);return o.getvalue()
def _draw_at(d,text,x,y,font,fill,center_x=None):
 if center_x is None:d.text((x,y),text,font=font,fill=fill);return
 b=d.textbbox((0,0),text,font=font);d.text((center_x-(b[2]-b[0])/2,y),text,font=font,fill=fill)
def win(m,k):
 W,H=1536,500;a=accent(k);im=Image.new('RGBA',(W,H),BG+(255,));frame(im,a);d=ImageDraw.Draw(im);cat=dl(CATS[k],480)
 if cat:
  scale=max(410/cat.width,410/cat.height);cat=cat.resize((int(cat.width*scale),int(cat.height*scale)),Image.Resampling.LANCZOS);cat=cat.crop(((cat.width-410)//2,(cat.height-410)//2,(cat.width+410)//2,(cat.height+410)//2));mask=Image.new('L',(410,410),0);ImageDraw.Draw(mask).rounded_rectangle((0,0,409,409),30,fill=235);cat.putalpha(mask);im.alpha_composite(cat,(40,45))
 title='GOOL CORE' if k=='core' else 'HT HUNTER' if k=='ht' else 'LATE RISK';d.text((55,45),title,font=F(32,True),fill=a);d.text((300,120),'ГОООЛ!',font=F(54,True),fill=a);d.text((520,75),'ЗАХОД!',font=F(92,True),fill=a);d.text((575,188),'✓  ГОЛ ПОДТВЕРЖДЁН',font=F(38,True),fill=a);d.text((620,240),'Сигнал успешно отработал',font=F(25),fill=WHITE);d.rounded_rectangle((1320,42,1490,90),16,fill=(8,12,20),outline=a,width=2);d.text((1337,54),'SIGNAL WON',font=F(21,True),fill=a)
 glow(im,(1010,110,1245,330),a);_draw_at(d,'● LIVE',0,135,F(25,True),a,1127);_draw_at(d,f"{m.home_score} : {m.away_score}",0,190,F(58,True),WHITE,1127);_draw_at(d,f"{m.minute}'",0,270,F(29,True),a,1127)
 hn,an=logos(getattr(m,'event_id',''));paste(im,logo(hn,95),1320,190);paste(im,logo(an,95),1440,190);d.text((575,322),getattr(m,'league','') or 'LIVE FOOTBALL',font=fit(d,getattr(m,'league',''),590,22,False),fill=MUTED);d.text((575,382),'ОДИН СИГНАЛ → ОДИН РЕЗУЛЬТАТ   •   5 МИНУТ ПОСЛЕ ГОЛА',font=F(20,True),fill=MUTED)
 o=BytesIO();im.convert('RGB').save(o,'PNG',optimize=True);return o.getvalue()
def render_engine_card(match,engine,score=0,delta=None,odd=None,result=None):
 k=kind(engine);delta=delta or {}
 return win(match,k) if result=='win' else sig(match,k,score,delta,odd)
