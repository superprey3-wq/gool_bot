"""GOOL CORE 2.0 Telegram PNG cards: analytics-first, odds-free."""
from __future__ import annotations
from io import BytesIO
import re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
import betb2b_market_signal as bms
W=1080;BG=(5,10,18);PANEL=(13,22,36);PANEL2=(19,31,49);TEXT=(247,249,252);MUTED=(151,166,188);GOLD=(255,184,48);GREEN=(82,220,118);RED=(244,104,104);CYAN=(61,178,255);YELLOW=(245,197,66);LINE=(45,63,88)
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
def _box(d,xy,title,value,sub='',accent=TEXT):
 d.rounded_rectangle(xy,18,fill=PANEL,outline=LINE,width=2);x1,y1,x2,y2=xy;d.text((x1+18,y1+13),title,font=_font(15,True),fill=MUTED);d.text((x1+18,y1+42),value,font=_fit(d,value,x2-x1-36,25,True),fill=accent)
 if sub:d.text((x1+18,y2-24),sub,font=_fit(d,sub,x2-x1-36,13,False),fill=MUTED)
def _ctx(p):return getattr(p,'analysis_context',None) or {}
def _num(d,k,default=0):
 try:return float(d.get(k,default) or default)
 except Exception:return float(default)
def _source_summary(ctx):
 ext=ctx.get('external_validation') or {};names=['Flashscore']
 if (ext.get('goal_api') or {}).get('matched'):names.append('GOAL API')
 if (ext.get('fotmob_deep') or ext.get('fotmob') or {}).get('matched'):names.append('FotMob')
 if (ext.get('scores365_deep') or ext.get('scores365') or {}).get('matched'):names.append('365Scores')
 hist=ctx.get('history') or {}
 if hist:names.append('Form/H2H')
 return names
def _prematch_line(ctx):
 h=ctx.get('history') or {}
 if not h:return ''
 parts=[]
 try:
  avg=float(h.get('historical_avg_total') or 0)
  if avg:parts.append(f'ср. тотал {avg:.2f}')
 except Exception:pass
 vals=[]
 for key in ('home','away','h2h'):
  row=h.get(key) or {}
  if int(row.get('n',0) or 0)>0 and row.get('over25') is not None:vals.append(float(row.get('over25') or 0))
 if vals:parts.append(f'ТБ2.5 {sum(vals)/len(vals)*100:.0f}%')
 return ' • '.join(parts)
def _reason(p,rs,probs):
 st=getattr(p,'stats',None) or getattr(p,'raw_stats',None) or {};ctx=_ctx(p);sc=ctx.get('strategies') or {};shots=sum(_pair(st,'shots'));sot=sum(_pair(st,'shots_on_target'));xg=sum(_pair(st,'xg'));xgot=sum(_pair(st,'xgot'));reasons=[]
 if xg>=1.4:reasons.append(f'xG {xg:.2f}: качество созданных моментов высокое.')
 elif xg>=.9:reasons.append(f'xG {xg:.2f}: матч создаёт достаточный объём моментов.')
 if sot>=5 or shots>=14:reasons.append(f'Темп подтверждён: {shots:g} ударов, {sot:g} в створ.')
 threat=_num(sc,'THREAT');mom=_num(sc,'MOMENTUM');dom=_num(sc,'DOMINATION')
 if max(threat,mom,dom)>=70:reasons.append(f'LIVE-давление устойчивое: пик аналитических блоков {max(threat,mom,dom):.0f}/100.')
 prem=_prematch_line(ctx)
 if prem:reasons.append(f'Предматчевый контекст поддерживает сценарий: {prem}.')
 ext=ctx.get('external_validation') or {};ext_reasons=list(ext.get('reasons') or [])
 if ext_reasons:reasons.append('Независимые источники: '+', '.join(str(x) for x in ext_reasons[:2])+'.')
 pgoal=int((probs or {}).get('one_goal',0) or 0)
 if pgoal:reasons.append(f'Модель оценивает вероятность ещё одного гола примерно в {pgoal}%.')
 return reasons[:5] or ['Сигнал сформирован совокупностью LIVE-статистики, темпа и исторического контекста.']
def _market_dot(draw,match):
 try:dot=bms.dot_for_match(match.home,match.away)
 except Exception:dot='🟡'
 col=GREEN if dot=='🟢' else RED if dot=='🔴' else YELLOW
 draw.ellipse((1000,46,1024,70),fill=col,outline=TEXT,width=1)
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind='entry',master=None,probabilities=None)->bytes:
 win=kind=='goal';accent=GREEN if win else GOLD;H=860 if win else 1320;img=Image.new('RGBA',(W,H),BG+(255,));d=ImageDraw.Draw(img)
 d.rounded_rectangle((24,20,W-24,112),24,fill=PANEL,outline=accent,width=2);d.text((52,36),'GOOL CORE 2.0',font=_font(36,True),fill=accent);d.text((52,78),'LIVE FOOTBALL • MULTI-SOURCE ANALYSIS',font=_font(16,True),fill=TEXT);d.rounded_rectangle((830,38,1028,93),16,outline=accent,width=2);d.text((862,53),'GOAL' if win else 'ENTRY',font=_font(20,True),fill=accent)
 if not win:_market_dot(d,match)
 hn,an=_logos(getattr(match,'event_id',''));_badge(img,d,180,282,_dl(hn),match.home,accent);_badge(img,d,900,282,_dl(an),match.away,accent);d.rounded_rectangle((390,202,690,365),28,fill=(9,19,31),outline=accent,width=3);_center(d,f'{match.home_score} : {match.away_score}',242,_font(66,True),TEXT);_center(d,'ПЕРЕРЫВ' if getattr(match,'is_halftime',False) else f"{match.minute}'",318,_font(27,True),accent)
 for x,n in ((180,match.home),(900,match.away)):
  f=_fit(d,n,330,30);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,383),n,font=f,fill=TEXT)
 _center(d,getattr(match,'league','') or 'LIVE FOOTBALL',434,_fit(d,getattr(match,'league','') or 'LIVE FOOTBALL',850,22,False),MUTED)
 if win:
  d.rounded_rectangle((70,520,1010,720),28,fill=(8,25,24),outline=GREEN,width=3);_center(d,'✓ СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ',555,_fit(d,'✓ СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ',850,38,True),GREEN);_center(d,'Модель ожидала продолжение голевой активности',620,_font(23,True),TEXT);_center(d,'Результат относится к футбольному сигналу, без привязки к коэффициенту',670,_fit(d,'Результат относится к футбольному сигналу, без привязки к коэффициенту',850,19,False),MUTED);footer=795
 else:
  probs=probabilities or {};rating=int(round(float(master if master is not None else getattr(pressure,'score',0) or 0)));pgoal=int(probs.get('one_goal',0) or 0);ctx=_ctx(pressure);sc=ctx.get('strategies') or {};sources=_source_summary(ctx)
  d.rounded_rectangle((55,480,1025,670),25,fill=PANEL2,outline=GOLD,width=2)
  d.text((85,505),'⚽ СИГНАЛ: ОЖИДАЕМ ГОЛ',font=_font(25,True),fill=GOLD)
  d.text((85,552),'Модель оценивает вероятность ещё одного гола',font=_fit(d,'Модель оценивает вероятность ещё одного гола',650,25,True),fill=TEXT)
  d.text((85,607),f'GOOL SCORE {rating}/100 · аналитический рейтинг модели',font=_fit(d,f'GOOL SCORE {rating}/100 · аналитический рейтинг модели',650,17,False),fill=MUTED)
  d.text((810,500),'P(ЕЩЁ ГОЛ)',font=_font(17,True),fill=MUTED)
  prob_text=f'{pgoal}%'
  pb=d.textbbox((0,0),prob_text,font=_font(52,True));d.text((910-(pb[2]-pb[0])/2,535),prob_text,font=_font(52,True),fill=GREEN)
  st=getattr(pressure,'stats',None) or getattr(pressure,'raw_stats',None) or {};xg=sum(_pair(st,'xg'));xgot=sum(_pair(st,'xgot'));shots=sum(_pair(st,'shots'));sot=sum(_pair(st,'shots_on_target'))
  _box(d,(55,705,285,810),'xG / xGoT',f'{xg:.2f} / {xgot:.2f}');_box(d,(300,705,530,810),'УДАРЫ',f'{shots:g}');_box(d,(545,705,775,810),'В СТВОР',f'{sot:g}');_box(d,(790,705,1025,810),'GOOL SCORE',f'{rating}/100',sub='внутренний рейтинг',accent=GOLD)
  _box(d,(55,835,285,940),'LIVE PRESSURE',f"{_num(sc,'MOMENTUM',getattr(pressure,'score',0)):.0f}/100");_box(d,(300,835,530,940),'THREAT',f"{_num(sc,'THREAT'):.0f}/100");_box(d,(545,835,775,940),'HISTORY',f"{_num(sc,'HISTORY',ctx.get('history_score',0)):.0f}/100");_box(d,(790,835,1025,940),'ИСТОЧНИКИ',f'{len(sources)}',sub=' • '.join(sources[:3]))
  d.rounded_rectangle((55,970,1025,1198),24,fill=PANEL,outline=LINE,width=2);d.text((85,993),'ПОЧЕМУ GOOL ДАЛ СИГНАЛ',font=_font(22,True),fill=GOLD);yy=1035
  for reason in _reason(pressure,recs or [],probs):
   for line in textwrap.wrap('• '+reason,width=76)[:2]:d.text((85,yy),line,font=_font(18),fill=TEXT);yy+=27
   if yy>1160:break
  d.text((85,1170),' • '.join(sources),font=_fit(d,' • '.join(sources),860,14,False),fill=MUTED);footer=1260
 _center(d,'GOOL AI 2.0 • LIVE FOOTBALL ANALYTICS',footer,_font(19,True),MUTED);out=BytesIO();img.convert('RGB').save(out,'PNG',optimize=True);return out.getvalue()
