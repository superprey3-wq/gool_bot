"""Premium compact Telegram PNG card for the actionable GOOL CORE LIVE signal."""
from __future__ import annotations
from io import BytesIO
import logging,re,textwrap
from typing import Any
import requests
from PIL import Image,ImageDraw,ImageFont
from live_engine import _feed
logger=logging.getLogger("signal_card");W=1080
BG=(6,11,19);PANEL=(14,23,37);PANEL2=(20,31,48);TEXT=(247,249,252);MUTED=(151,166,188);GOLD=(255,184,48);GREEN=(83,216,121);LINE=(44,61,84)
def _font(s,b=False):
 for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if b else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
  try:return ImageFont.truetype(p,s)
  except OSError:pass
 return ImageFont.load_default()
def _fields(r):
 o={}
 for t in r.split("¬"):
  if "÷" in t:k,v=t.split("÷",1);o.setdefault(k,v)
 return o
def _logos(eid):
 b=_feed("f_1_0_0_en_1") or "";n=f"AA÷{eid}¬"
 for c in b.split("~"):
  if n in c:
   f=_fields(c);return f.get("OA",""),f.get("OB","")
 return "",""
def _dl(fn):
 if not fn:return None
 try:
  r=requests.get(f"https://static.flashscore.com/res/image/data/{fn}",timeout=5,headers={"User-Agent":"Mozilla/5.0"})
  if r.ok:return Image.open(BytesIO(r.content)).convert("RGBA")
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
 r=59;d.ellipse((x-r-7,y-r-7,x+r+7,y+r+7),outline=accent,width=3);d.ellipse((x-r,y-r,x+r,y+r),fill=PANEL2,outline=LINE,width=2)
 if logo:
  bb=logo.getbbox();logo=logo.crop(bb) if bb else logo;s=min(102/max(1,logo.width),102/max(1,logo.height));logo=logo.resize((max(1,int(logo.width*s)),max(1,int(logo.height*s))),Image.Resampling.LANCZOS);img.alpha_composite(logo,(x-logo.width//2,y-logo.height//2))
 else:
  t="".join(x[0] for x in re.findall(r"[A-Za-zА-Яа-я0-9]+",name)[:2]).upper() or "?";f=_font(28,True);b=d.textbbox((0,0),t,font=f);d.text((x-(b[2]-b[0])/2,y-(b[3]-b[1])/2),t,font=f,fill=TEXT)
def _pair(st,k):
 try:a,b=st.get(k,(0,0));return float(a or 0),float(b or 0)
 except:return 0.,0.
def _best(rs):return next((r for r in (rs or []) if r.get("best_concrete_bet")),None) or next((r for r in (rs or []) if r.get("best_bet")),None)
def _extra(rs,k):return next((r for r in (rs or []) if r.get("extra_market")==k),None)
def _sources(r):
 if not r:return "—"
 sp=r.get("source_prices") or []
 return "  •  ".join(f"{str(x.get('source','LIVE')).split('/')[0]} {float(x.get('odd',0)):.2f}" for x in sp[:3]) if sp else f"{r.get('source','LIVE')} {float(r.get('odd',0)):.2f}"
def _status(r):
 s=str((r or {}).get("external_market_status") or (r or {}).get("market_status") or (r or {}).get("market_consensus") or "")
 return {"STEAM":"🔥 ПРОГРУЗ","CONFIRMED":"✓ ПОДТВЕРЖДЕНО","DISAGREE":"⚠ РАСХОЖДЕНИЕ","CONFLICT":"⚠ ПРОТИВ РЫНКА","EARLY":"РАННИЙ РЫНОК","SINGLE_SOURCE":"1 ИСТОЧНИК"}.get(s,s)
def _bet(r):
 if not r:return "НЕТ НАДЁЖНОГО РЫНКА"
 o=float(r.get("odd",0) or 0);kind=str(r.get("market_type") or "")
 if kind=="BTTS":return f"ОБЕ ЗАБЬЮТ — ДА  @ {o:.2f}"
 if kind=="FIRST_HALF_GOAL":return f"ТБ {float(r['line']):g} В 1-М ТАЙМЕ  @ {o:.2f}"
 if kind.startswith("TEAM_TOTAL") or r.get("team_name"):return f"ИТБ {r.get('team_name','КОМАНДЫ')} {float(r.get('line',.5)):g}  @ {o:.2f}"
 if r.get("line") is not None:return f"ТБ {float(r['line']):g}  @ {o:.2f}"
 return f"LIVE  @ {o:.2f}"
def _box(d,xy,title,value,sub="",accent=TEXT):
 d.rounded_rectangle(xy,18,fill=PANEL,outline=LINE,width=2);x1,y1,x2,y2=xy;d.text((x1+18,y1+13),title,font=_font(15,True),fill=MUTED);d.text((x1+18,y1+42),value,font=_fit(d,value,x2-x1-36,25,True),fill=accent)
 if sub:d.text((x1+18,y2-24),sub,font=_fit(d,sub,x2-x1-36,13,False),fill=MUTED)
def _reason(match,p,rs,probs):
 st=getattr(p,"stats",None) or getattr(p,"raw_stats",None) or {};shots=sum(_pair(st,"shots"));sot=sum(_pair(st,"shots_on_target"));xg=sum(_pair(st,"xg"));a=[]
 if xg>=1.4:a.append("Качество созданных моментов высокое.")
 if sot>=5 or shots>=15:a.append("Темп матча подтверждается ударами и створами.")
 if int((probs or {}).get("one_goal",0) or 0)>=70:a.append(f"Модель: ещё гол {(probs or {}).get('one_goal')}%.")
 if any(int(r.get("source_count",1) or 1)>=2 for r in (rs or [])):a.append("Коэффициент подтверждён несколькими источниками.")
 return " ".join(a[:3] or ["LIVE-модель, профиль лиги и рынок одновременно подтверждают вход."])
def render_signal_card(match:Any,pressure:Any,recs:list[dict[str,Any]]|None=None,kind="entry",master=None,probabilities=None)->bytes:
 win=kind=="goal";accent=GREEN if win else GOLD;H=790 if win else 1360;img=Image.new("RGBA",(W,H),BG+(255,));d=ImageDraw.Draw(img);d.rounded_rectangle((24,20,W-24,108),24,fill=PANEL,outline=accent,width=2);d.text((52,38),"GOOL CORE",font=_font(35,True),fill=accent);d.text((52,78),"LIVE FOOTBALL • MARKET SELECTION",font=_font(17,True),fill=TEXT);d.rounded_rectangle((840,38,1028,91),16,outline=accent,width=2);d.text((870,52),"WIN" if win else "LIVE SIGNAL",font=_font(20,True),fill=accent)
 hn,an=_logos(getattr(match,"event_id",""));_badge(img,d,180,275,_dl(hn),match.home,accent);_badge(img,d,900,275,_dl(an),match.away,accent);d.rounded_rectangle((390,200,690,360),28,fill=(9,19,31),outline=accent,width=3);_center(d,f"{match.home_score} : {match.away_score}",240,_font(65,True),TEXT);_center(d,"ПЕРЕРЫВ" if getattr(match,"is_halftime",False) else f"{match.minute}'",315,_font(27,True),accent)
 for x,n in ((180,match.home),(900,match.away)):
  f=_fit(d,n,330,30);b=d.textbbox((0,0),n,font=f);d.text((x-(b[2]-b[0])/2,375),n,font=f,fill=TEXT)
 _center(d,getattr(match,"league","") or "LIVE FOOTBALL",425,_fit(d,getattr(match,"league","") or "LIVE FOOTBALL",850,22,False),MUTED)
 if win:
  d.rounded_rectangle((70,515,1010,675),28,fill=(8,25,24),outline=GREEN,width=3);_center(d,"✓ СТАВКА ЗАШЛА",550,_font(42,True),GREEN);_center(d,"Результат подтверждён LIVE-данными",615,_font(24),TEXT);footer=735
 else:
  rs=recs or [];probs=probabilities or {};rating=int(round(float(master if master is not None else getattr(pressure,"score",0) or 0)));best=_best(rs);btts=_extra(rs,"BTTS_YES");fh=_extra(rs,"FIRST_HALF_DYNAMIC");d.rounded_rectangle((55,475,1025,635),25,fill=PANEL2,outline=GOLD,width=2);d.text((85,500),"РЕШЕНИЕ GOOL",font=_font(17,True),fill=MUTED);d.text((85,530),"⭐ ЛУЧШАЯ СТАВКА",font=_font(24,True),fill=GOLD);d.text((85,570),_bet(best),font=_fit(d,_bet(best),700,35,True),fill=TEXT);d.text((790,510),"РЕЙТИНГ",font=_font(16,True),fill=MUTED);d.text((790,545),f"{rating}/100",font=_font(39,True),fill=GOLD);d.text((85,608),f"{_sources(best)}   {_status(best)}",font=_fit(d,f"{_sources(best)}   {_status(best)}",890,16,False),fill=GREEN if best else MUTED)
  st=getattr(pressure,"stats",None) or getattr(pressure,"raw_stats",None) or {};xg=sum(_pair(st,"xg"));xgot=sum(_pair(st,"xgot"));shots=sum(_pair(st,"shots"));sot=sum(_pair(st,"shots_on_target"));_box(d,(55,660,285,765),"xG / xGoT",f"{xg:.2f} / {xgot:.2f}");_box(d,(300,660,530,765),"УДАРЫ",f"{shots:g}");_box(d,(545,660,775,765),"В СТВОР",f"{sot:g}");_box(d,(790,660,1025,765),"ЕЩЁ ГОЛ",f"{int(probs.get('one_goal',0) or 0)}%",accent=GREEN)
  d.text((65,800),"РЫНОК • ПОДТВЕРЖДЕНИЯ",font=_font(20,True),fill=GOLD);goals=int(match.home_score or 0)+int(match.away_score or 0);one=next((r for r in rs if r.get("scope")=="FULL_TIME" and r.get("line") is not None and abs(float(r.get("line"))-(goals+.5))<1e-9),None);_box(d,(55,835,1025,935),f"АКТУАЛЬНЫЙ ТОТАЛ • ТБ{goals+.5:g}",_sources(one),_status(one),GREEN if one else MUTED)
  if int(getattr(match,"minute",0) or 0)<=45 and not getattr(match,"is_halftime",False):title=f"1-Й ТАЙМ • ТБ{float(fh['line']):g}" if fh and fh.get("line") is not None else "1-Й ТАЙМ";_box(d,(55,955,530,1065),title,_sources(fh),_status(fh),GREEN if fh else MUTED)
  else:_box(d,(55,955,530,1065),"1-Й ТАЙМ","ЗАКРЫТ","",MUTED)
  _box(d,(545,955,1025,1065),"ОБЕ ЗАБЬЮТ • ДА",_sources(btts),_status(btts),GREEN if btts else MUTED);d.rounded_rectangle((55,1090,1025,1248),24,fill=PANEL,outline=LINE,width=2);d.text((85,1115),"ПОЧЕМУ ИМЕННО ЭТА СТАВКА",font=_font(21,True),fill=GOLD);yy=1154
  for line in textwrap.wrap(_reason(match,pressure,rs,probs),width=72)[:3]:d.text((85,yy),line,font=_font(20),fill=TEXT);yy+=31
  d.text((85,1215),"Flashscore • LSApp • Bovada • Kambi • xG/xGoT consensus",font=_font(15),fill=MUTED);footer=1305
 _center(d,"GOOL AI • LIVE FOOTBALL ANALYTICS",footer,_font(19,True),MUTED);out=BytesIO();img.convert("RGB").save(out,"PNG",optimize=True);return out.getvalue()
