"""GOOL CORE 2.0 Telegram PNG cards: best bet, alternatives and market movement."""
from __future__ import annotations
from io import BytesIO
import re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
W=1080;BG=(5,10,18);PANEL=(13,22,36);PANEL2=(19,31,49);TEXT=(247,249,252);MUTED=(151,166,188);GOLD=(255,184,48);GREEN=(82,220,118);RED=(244,104,104);CYAN=(61,178,255);LINE=(45,63,88)
def _font(s,b=False):
 for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if b else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
  try:return ImageFont.truetype(p,s)
  except OSError:pass
 return ImageFont.load_default()
def _fields(r):
 o={}
 for t in str(r or '').split('¬'):
  if '÷' in t:k,v=t.split('÷',1);o.setdefault(k,v)
 return o
def _logos(eid):
 try:b=_feed('f_1_0_0_en_1') or ''
 except Exception:return '',''
 n=f'AA÷{eid}¬'
 for c in b.split('~'):
  if n in c:
   f=_fields(c);return f.get('OA',''),f.get('OB','')
 return '',''
def _dl(fn):
 if not fn:return None
 try:
  r=requests.get(f'https://static.flashscore.com/res/image/data/{fn}',timeout=5,headers={'User-Agent':'Mozilla/5.0'})
  if r.ok:return Image.open(BytesIO(r.content)).convert('RGBA')
 except Exception:pass
 return None
def _fit(d,t,w,s=32,b=True):
 for z in range(s,15,-2):
  f=_font(z,b)
  if d.textbbox((0,0),str(t),font=f)[2]<=w:return f
 return _font(16,b)
def _center(d,t,y,f,c):
 b=d.textbbox((0,0),str(t),font=f);d.text(((W-(b[2]-b[0]))/2,y),str(t),font=f,fill=c)
def _badge(img,d,x,y,logo,name,accent):
 r=60;d.ellipse((x-r-8,y-r-8,x+r+8,y+r+8),outline=accent,width=3);d.ellipse((x-r,y-r,x+r,y+r),fill=PANEL2,outline=LINE,width=2)
 if logo:
  bb=logo.getbbox();logo=logo.crop(bb) if bb else logo;s=min(104/max(1,logo.width),104/max(1,logo.height));logo=logo.resize((max(1,int(logo.width*s)),max(1,int(logo.height*s))),Image.Resampling.LANCZOS);img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
 else:
  t=''.join(x[0] for x in re.findall(r'[A-Za-zА-Яа-я0-9]+',str(name))[:2]).upper() or '?';f=_font(28,True);b=d.textbbox((0,0),t,font=f);d.text((x-(b[2]-b[0])/2,y-(b[3]-b[1])/2),t,font=f,fill=TEXT)
def _pair(st,k):
 try:a,b=st.get(k,(0,0));return float(a or 0),float(b or 0)
 except Exception:return 0.,0.
def _best(rs):return next((r for r in (rs or []) if r.get('best_concrete_bet')),None) or next((r for r in (rs or []) if r.get('best_bet')),None) or ((rs or [None])[0])
def _alternatives(rs,best):
 rows=[]
 for r in rs or []:
  if r is best or r.get('odd') is None:continue
  if str(r.get('scope') or '').upper()!='FULL_TIME':continue
  kind=str(r.get('market_type') or 'TOTAL').upper()
  if kind not in {'TOTAL','BTTS','TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'} and r.get('goal_step') is None:continue
  if r.get('selector_reject'):continue
  rows.append(r)
 rows.sort(key=lambda r:float(r.get('selector_score',-999) or -999),reverse=True);return rows[:2]
def _bet(r):
 if not r:return 'НЕТ НАДЁЖНОГО РЫНКА'
 try:o=float(r.get('odd',0) or 0)
 except Exception:o=0
 kind=str(r.get('market_type') or r.get('market') or '').upper();line=r.get('line');team=str(r.get('team_name') or 'КОМАНДЫ')
 if kind=='BTTS':label='ОБЕ ЗАБЬЮТ — ДА'
 elif kind in {'TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'} or r.get('team_name'):label=f'ИТБ {team} {float(line):g}'
 elif str(r.get('scope') or '').upper()=='FIRST_HALF':label=f'ТБ {float(line):g} В 1-М ТАЙМЕ'
 elif str(r.get('scope') or '').upper()=='SECOND_HALF':label=f'ТБ {float(line):g} ВО 2-М ТАЙМЕ'
 elif line is not None:label=f'ТБ {float(line):g}'
 else:label='LIVE MARKET'
 return f'{label}  @ {o:.2f}' if o>1 else label
def _sources(r):
 if not r:return '—'
 sp=r.get('source_prices') or []
 if sp:return '  •  '.join(f"{str(x.get('source','LIVE')).split('/')[0]} {float(x.get('odd',0)):.2f}" for x in sp[:3])
 try:return f"{r.get('source','LIVE')} {float(r.get('odd',0)):.2f}"
 except Exception:return str(r.get('source','LIVE'))
def _movement(r):
 if not r:return 'РЫНОК —',MUTED
 st=str(r.get('movement_status') or r.get('external_market_status') or r.get('market_status') or r.get('market_consensus') or '').upper()
 if r.get('correlated_steam'):label='🔥 ПРОГРУЗ СВЯЗАННЫХ РЫНКОВ';col=GREEN
 elif st=='CONFIRMED_STEAM':label='🔥 ПОДТВЕРЖДЁННЫЙ ПРОГРУЗ';col=GREEN
 elif st=='STEAM':label='🔥 ПРОГРУЗ';col=GREEN
 elif st=='REVERSAL':label='↩ РАЗВОРОТ РЫНКА';col=RED
 elif st in {'CONFLICT','DISAGREE'}:label='⚠ РЫНОК ПРОТИВ';col=RED
 elif st in {'CONFIRMED'}:label='✓ ПОДТВЕРЖДЕНО';col=GREEN
 elif st in {'SINGLE_SOURCE','EARLY'}:label='РАННИЙ РЫНОК';col=MUTED
 else:label='ЛИНИЯ СТАБИЛЬНА';col=MUTED
 try:
  drop=float(r.get('movement_drop_pct') or 0)
  if abs(drop)>=0.1:label+=f' • {drop:+.1f}%'
 except Exception:pass
 return label,col
def _box(d,xy,title,value,sub='',accent=TEXT):
 d.rounded_rectangle(xy,18,fill=PANEL,outline=LINE,width=2);x1,y1,x2,y2=xy;d.text((x1+18,y1+13),title,font=_font(15,True),fill=MUTED);d.text((x1+18,y1+42),value,font=_fit(d,value,x2-x1-36,25,True),fill=accent)
 if sub:d.text((x1+18,y2-24),sub,font=_fit(d,sub,x2-x1-36,13,False),fill=MUTED)
def _market_probability(best,probs):
 if best:
  try:
   v=float(best.get('selector_confidence'))
   if v>0:return int(round(v))
  except Exception:pass
 return int((probs or {}).get('one_goal',0) or 0)
def _probability_label(best):
 if not best:return 'ВЕРОЯТНОСТЬ'
 kind=str(best.get('market_type') or 'TOTAL').upper()
 if kind in {'TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'}:
  return 'P(ИТБ)'
 if kind=='BTTS':return 'P(ОЗ)'
 return 'P(СТАВКИ)'
def _reason(p,rs,probs):
 st=getattr(p,'stats',None) or getattr(p,'raw_stats',None) or {};shots=sum(_pair(st,'shots'));sot=sum(_pair(st,'shots_on_target'));xg=sum(_pair(st,'xg'));a=[];best=_best(rs or [])
 if best:
  try:conf=float(best.get('selector_confidence') or 0);imp=float(best.get('selector_implied') or (100/float(best.get('odd'))));edge=float(best.get('selector_edge') if best.get('selector_edge') is not None else conf-imp)
  except Exception:conf=imp=edge=0
  if conf>0:a.append(f'Вероятность выбранного рынка {conf:.0f}%; edge {edge:+.1f} п.п.')
  kind=str(best.get('market_type') or '').upper()
  if kind in {'TEAM_TOTAL_HOME','TEAM_TOTAL_AWAY'}:
   needed=int(best.get('team_goals_needed') or 1);ev=int(best.get('team_evidence') or 0);team=str(best.get('team_name') or 'команде');a.append(f'{team}: нужно ещё {needed} гол.; подтверждений атаки {ev}.')
 if best and best.get('correlated_steam'):a.append('Связанные рынки двигаются в сторону выбранной ставки.')
 if not a and xg>=1.4:a.append('Качество созданных моментов высокое.')
 if not a and (sot>=5 or shots>=15):a.append('Темп подтверждается ударами и створами.')
 if any(int(r.get('source_count',1) or 1)>=2 for r in (rs or [])):a.append('Цена подтверждена несколькими LIVE-источниками.')
 return ' '.join(a[:3] or ['LIVE-модель, профиль лиги и рынок одновременно подтверждают выбранный вход.'])
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind='entry',master=None,probabilities=None)->bytes:
 win=kind=='goal';accent=GREEN if win else GOLD;H=820 if win else 1320;img=Image.new('RGBA',(W,H),BG+(255,));d=ImageDraw.Draw(img)
 d.rounded_rectangle((24,20,W-24,112),24,fill=PANEL,outline=accent,width=2);d.text((52,36),'GOOL CORE 2.0',font=_font(36,True),fill=accent);d.text((52,78),'LIVE FOOTBALL • BEST BET • MARKET STEAM',font=_font(16,True),fill=TEXT);d.rounded_rectangle((830,38,1028,93),16,outline=accent,width=2);d.text((870,53),'WIN' if win else 'ENTRY',font=_font(20,True),fill=accent)
 hn,an=_logos(getattr(match,'event_id',''));_badge(img,d,180,282,_dl(hn),match.home,accent);_badge(img,d,900,282,_dl(an),match.away,accent);d.rounded_rectangle((390,202,690,365),28,fill=(9,19,31),outline=accent,width=3);_center(d,f'{match.home_score} : {match.away_score}',242,_font(66,True),TEXT);_center(d,'ПЕРЕРЫВ' if getattr(match,'is_halftime',False) else f"{match.minute}'",318,_font(27,True),accent)
 for x,n in ((180,match.home),(900,match.away)):
  f=_fit(d,n,330,30);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,383),n,font=f,fill=TEXT)
 _center(d,getattr(match,'league','') or 'LIVE FOOTBALL',434,_fit(d,getattr(match,'league','') or 'LIVE FOOTBALL',850,22,False),MUTED);rs=recs or [];best=_best(rs)
 if win:
  d.rounded_rectangle((70,520,1010,705),28,fill=(8,25,24),outline=GREEN,width=3);_center(d,'✓ СТАВКА ЗАШЛА',550,_font(40,True),GREEN);_center(d,_bet(best),606,_fit(d,_bet(best),850,31,True),TEXT);_center(d,'Результат рассчитан по выбранному primary-рынку',662,_font(20),MUTED);footer=765
 else:
  probs=probabilities or {};rating=int(round(float(master if master is not None else getattr(pressure,'score',0) or 0)));alts=_alternatives(rs,best);mv,mvcol=_movement(best)
  d.rounded_rectangle((55,480,1025,675),25,fill=PANEL2,outline=GOLD,width=2);d.text((85,503),'⭐ ЛУЧШАЯ СТАВКА',font=_font(24,True),fill=GOLD);d.text((85,552),_bet(best),font=_fit(d,_bet(best),730,35,True),fill=TEXT);d.text((85,607),_sources(best),font=_fit(d,_sources(best),680,16,False),fill=MUTED);d.text((85,635),mv,font=_fit(d,mv,720,18,True),fill=mvcol);d.text((835,505),'GOOL',font=_font(16,True),fill=MUTED);d.text((825,538),f'{rating}/100',font=_font(39,True),fill=GOLD)
  d.text((65,700),'АЛЬТЕРНАТИВЫ',font=_font(18,True),fill=MUTED)
  if alts:
   width=475 if len(alts)>1 else 970
   for i,r in enumerate(alts):
    x1=55+i*490;x2=x1+width if len(alts)==1 else x1+475;sub,_c=_movement(r);_box(d,(x1,734,x2,832),f'№{i+2}',_bet(r),sub,GREEN)
  else:_box(d,(55,734,1025,832),'АЛЬТЕРНАТИВ НЕТ','ТОЛЬКО ОДИН РЫНОК ПРОШЁЛ ФИЛЬТР','',MUTED)
  st=getattr(pressure,'stats',None) or getattr(pressure,'raw_stats',None) or {};xg=sum(_pair(st,'xg'));xgot=sum(_pair(st,'xgot'));shots=sum(_pair(st,'shots'));sot=sum(_pair(st,'shots_on_target'));mp=_market_probability(best,probs)
  _box(d,(55,865,285,970),'xG / xGoT',f'{xg:.2f} / {xgot:.2f}');_box(d,(300,865,530,970),'УДАРЫ',f'{shots:g}');_box(d,(545,865,775,970),'В СТВОР',f'{sot:g}');_box(d,(790,865,1025,970),_probability_label(best),f'{mp}%',accent=GREEN)
  d.rounded_rectangle((55,1000,1025,1188),24,fill=PANEL,outline=LINE,width=2);d.text((85,1025),'ПОЧЕМУ ИМЕННО ЭТА СТАВКА',font=_font(21,True),fill=GOLD);yy=1065
  for line in textwrap.wrap(_reason(pressure,rs,probs),width=72)[:3]:d.text((85,yy),line,font=_font(20),fill=TEXT);yy+=31
  d.text((85,1152),'Flashscore • LSApp • Bovada • Kambi • xG/xGoT consensus • Market Movement',font=_font(14),fill=MUTED);footer=1260
 _center(d,'GOOL AI 2.0 • LIVE FOOTBALL ANALYTICS',footer,_font(19,True),MUTED);out=BytesIO();img.convert('RGB').save(out,'PNG',optimize=True);return out.getvalue()
