"""Compact premium Telegram PNG cards for GOOL actionable LIVE signals."""
from __future__ import annotations
from io import BytesIO
import logging,re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card")
W=1080
BG=(7,12,20);PANEL=(15,24,38);PANEL2=(20,30,46);TEXT=(246,248,252);MUTED=(154,168,190);GOLD=(255,181,45);GREEN=(87,210,119);LINE=(45,62,86)
def _font(size,bold=False):
 for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
  try:return ImageFont.truetype(p,size)
  except OSError:pass
 return ImageFont.load_default()
def _fields(r):
 o={}
 for t in r.split("¬"):
  if "÷" in t:k,v=t.split("÷",1);o.setdefault(k,v)
 return o
def _logo_names(eid):
 b=_feed("f_1_0_0_en_1");n=f"AA÷{eid}¬"
 if not b or n not in b:return "",""
 for c in b.split("~"):
  if n in c:
   f=_fields(c);return f.get("OA",""),f.get("OB","")
 return "",""
def _download_logo(fn):
 if not fn:return None
 try:
  r=requests.get(f"https://static.flashscore.com/res/image/data/{fn}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
  if r.ok:return Image.open(BytesIO(r.content)).convert("RGBA")
 except Exception:pass
 return None
def _initials(n):
 w=re.findall(r"[A-Za-zА-Яа-я0-9]+",n);return "".join(x[0] for x in w[:2]).upper() if w else "?"
def _fit(d,t,w,start=32,bold=True):
 for s in range(start,16,-2):
  f=_font(s,bold)
  if d.textbbox((0,0),str(t),font=f)[2]<=w:return f
 return _font(17,bold)
def _center(d,t,y,f,c):
 b=d.textbbox((0,0),t,font=f);d.text(((W-(b[2]-b[0]))/2,y),t,font=f,fill=c)
def _badge(img,d,x,y,logo,name,won=False):
 a=GREEN if won else GOLD;r=60;d.ellipse((x-r-7,y-r-7,x+r+7,y+r+7),outline=a,width=3);d.ellipse((x-r,y-r,x+r,y+r),fill=PANEL2,outline=LINE,width=2)
 if logo:
  bb=logo.getbbox();logo=logo.crop(bb) if bb else logo;s=min(105/max(1,logo.width),105/max(1,logo.height));logo=logo.resize((max(1,int(logo.width*s)),max(1,int(logo.height*s))),Image.Resampling.LANCZOS);img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
 else:
  t=_initials(name);f=_font(30,True);bb=d.textbbox((0,0),t,font=f);d.text((x-(bb[2]-bb[0])/2,y-(bb[3]-bb[1])/2),t,font=f,fill=TEXT)
def _best(rs):
 rs=rs or [];return next((r for r in rs if r.get("best_bet")),None) or next((r for r in rs if r.get("full_match_best")),None) or next((r for r in rs if r.get("scope")=="FULL_TIME" and r.get("goal_step")==1),None)
def _extra(rs,k):return next((r for r in (rs or []) if r.get("extra_market")==k),None)
def _pair(stats,key):
 try:a,b=stats.get(key,(0,0));return float(a or 0),float(b or 0)
 except Exception:return 0.,0.
def _sources(r):
 if not r:return "—"
 sp=r.get("source_prices") or []
 if sp:return " | ".join(f"{str(x.get('source','LIVE')).split('/')[0]} {float(x.get('odd',0)):.2f}" for x in sp[:3])
 return f"{r.get('source','LIVE')} {float(r.get('odd',0)):.2f}"
def _status(r):
 if not r:return ""
 s=str(r.get("external_market_status") or r.get("market_consensus") or "")
 return {"STEAM":"🔥 STEAM","CONFIRMED":"✓ CONFIRMED","DISAGREE":"⚠ DISAGREE","CONFLICT":"⚠ CONFLICT","EARLY":"EARLY","SINGLE_SOURCE":"1 SOURCE"}.get(s,s)
def _box(d,xy,title,value,sub="",accent=TEXT):
 d.rounded_rectangle(xy,18,fill=PANEL,outline=LINE,width=2);x1,y1,x2,y2=xy;d.text((x1+18,y1+13),title,font=_font(16,True),fill=MUTED);d.text((x1+18,y1+43),value,font=_fit(d,value,x2-x1-36,26,True),fill=accent)
 if sub:d.text((x1+18,y2-25),sub,font=_fit(d,sub,x2-x1-36,14,False),fill=MUTED)
def _reason(match,pressure,recs,probs):
 st=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {};shots=sum(_pair(st,"shots"));sot=sum(_pair(st,"shots_on_target"));xg=sum(_pair(st,"xg"));p=int((probs or {}).get("one_goal",0) or 0);a=[]
 if xg>=1.6:a.append("Высокое качество моментов по xG/xGoT.")
 if sot>=6 or shots>=18:a.append("Высокий LIVE-темп по ударам и створам.")
 if p>=70:a.append(f"Модель даёт {p}% на ещё один гол.")
 if any((r.get("source_count",1) or 1)>=2 for r in (recs or [])):a.append("Рынок подтверждён независимыми источниками.")
 return " ".join(a[:2] or ["LIVE-модель, контекст лиги и рынок подтверждают сигнал."])
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind="entry",master=None,probabilities=None)->bytes:
 win=kind=="goal";a=GREEN if win else GOLD;H=790 if win else 1380;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);d.rounded_rectangle((24,20,W-24,108),24,fill=PANEL,outline=a,width=2);d.text((52,39),"♛ GOOL CORE",font=_font(34,True),fill=a);d.text((52,78),"ГЛАВНЫЙ LIVE-СИГНАЛ",font=_font(18,True),fill=TEXT);d.rounded_rectangle((835,38,1028,91),16,outline=a,width=2);d.text((866,52),"SIGNAL WON" if win else "LIVE SIGNAL",font=_font(20,True),fill=a)
 hn,an=_logo_names(getattr(match,"event_id",""));_badge(img,d,180,280,_download_logo(hn),match.home,win);_badge(img,d,900,280,_download_logo(an),match.away,win);d.rounded_rectangle((390,205,690,365),28,fill=(10,20,32),outline=a,width=3);_center(d,f"{match.home_score} : {match.away_score}",245,_font(66,True),TEXT);_center(d,"ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'",322,_font(27,True),a)
 for x,n in ((180,match.home),(900,match.away)):
  f=_fit(d,n,330);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,380),n,font=f,fill=TEXT)
 _center(d,getattr(match,"league","") or "LIVE FOOTBALL",430,_fit(d,getattr(match,"league","") or "LIVE FOOTBALL",850,23,False),MUTED)
 if win:
  d.rounded_rectangle((70,520,1010,675),28,fill=(9,24,25),outline=GREEN,width=3);_center(d,"✓ ГОЛ ПОДТВЕРЖДЁН",555,_font(39,True),GREEN);_center(d,"Сигнал успешно отработал",615,_font(25),TEXT);footer=735
 else:
  rs=recs or [];probs=probabilities or {};rating=int(round(float(master if master is not None else getattr(pressure,"score",0) or 0)));best=_best(rs);btts=_extra(rs,"BTTS_YES");fh=_extra(rs,"FIRST_HALF_OVER_05");d.rounded_rectangle((55,485,1025,620),24,fill=PANEL2,outline=LINE,width=2);d.text((90,510),"РЕЙТИНГ GOOL",font=_font(19,True),fill=MUTED);d.text((90,545),f"{rating}/100",font=_font(43,True),fill=GOLD);d.line((350,505,350,600),fill=LINE,width=2);d.text((390,510),"ОСНОВНОЙ РЫНОК",font=_font(19,True),fill=MUTED)
  if best:d.text((390,544),f"ТБ {float(best['line']):g} @ {float(best['odd']):.2f}",font=_font(34,True),fill=TEXT);d.text((390,584),f"{_sources(best)}  {_status(best)}",font=_fit(d,f"{_sources(best)}  {_status(best)}",600,17,False),fill=GREEN)
  else:d.text((390,552),"LIVE-кэф не найден",font=_font(26,True),fill=MUTED)
  st=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {};xg=sum(_pair(st,"xg"));shots=sum(_pair(st,"shots"));sot=sum(_pair(st,"shots_on_target"));danger=sum(_pair(st,"dangerous_attacks"));_box(d,(55,645,285,750),"xG / xGoT",f"{xg:.2f}");_box(d,(300,645,530,750),"УДАРЫ",f"{shots:g}");_box(d,(545,645,775,750),"В СТВОР",f"{sot:g}");_box(d,(790,645,1025,750),"ОПАСНЫЕ АТАКИ",f"{danger:g}")
  d.text((65,785),"LIVE РЫНКИ • НЕЗАВИСИМОЕ ПОДТВЕРЖДЕНИЕ",font=_font(21,True),fill=GOLD);p1=int(probs.get("one_goal",0) or 0);one=next((r for r in rs if r.get("goal_step")==1),None);_box(d,(55,825,1025,925),"ЕЩЁ 1 ГОЛ",f"Модель {p1}%",f"{_sources(one)}  {_status(one)}",GREEN)
  if int(getattr(match,"minute",0) or 0)<=45 and int(getattr(match,"home_score",0) or 0)+int(getattr(match,"away_score",0) or 0)==0:_box(d,(55,945,530,1055),"ГОЛ В 1-М ТАЙМЕ • ТБ0.5",_sources(fh),_status(fh),GREEN if fh else MUTED)
  else:_box(d,(55,945,530,1055),"ГОЛ В 1-М ТАЙМЕ","РЫНОК ЗАКРЫТ","",MUTED)
  _box(d,(545,945,1025,1055),"ОБЕ ЗАБЬЮТ • ДА",_sources(btts),_status(btts),GREEN if btts else MUTED);d.rounded_rectangle((55,1080,1025,1265),24,fill=PANEL,outline=LINE,width=2);d.text((85,1105),"ПОЧЕМУ СИГНАЛ",font=_font(22,True),fill=GOLD);yy=1145
  for line in textwrap.wrap(_reason(match,pressure,rs,probs),width=70)[:3]:d.text((85,yy),line,font=_font(21),fill=TEXT);yy+=34
  d.text((85,1230),"Flashscore / LSApp / Bovada / Kambi • xG/xGoT enrichment",font=_font(16),fill=MUTED);footer=1325
 _center(d,"GOOL AI  •  LIVE FOOTBALL ANALYTICS",footer,_font(20,True),MUTED);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
