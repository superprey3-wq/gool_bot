"""PNG infographic cards for GOOL BEST BET entry/result."""
from __future__ import annotations
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
W=1080;BG=(5,10,18);PANEL=(13,22,36);PANEL2=(19,31,49);TEXT=(247,249,252);MUTED=(151,166,188);GOLD=(255,184,48);GREEN=(82,220,118);RED=(244,104,104);CYAN=(61,178,255);LINE=(45,63,88)
def _font(s,b=False):
 for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf","/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if b else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]:
  try:return ImageFont.truetype(p,s)
  except OSError:pass
 return ImageFont.load_default()
def _fit(d,t,w,s=34,b=True):
 for z in range(s,15,-2):
  f=_font(z,b)
  if d.textbbox((0,0),str(t),font=f)[2]<=w:return f
 return _font(16,b)
def _center(d,t,y,f,c):
 b=d.textbbox((0,0),str(t),font=f);d.text(((W-(b[2]-b[0]))/2,y),str(t),font=f,fill=c)
def _box(d,x,y,w,h,title,value,accent=TEXT,sub=''):
 d.rounded_rectangle((x,y,x+w,y+h),18,fill=PANEL,outline=LINE,width=2);d.text((x+18,y+14),title,font=_font(15,True),fill=MUTED);d.text((x+18,y+46),str(value),font=_fit(d,value,w-36,27,True),fill=accent)
 if sub:d.text((x+18,y+h-25),sub,font=_fit(d,sub,w-36,13,False),fill=MUTED)
def render_entry(m,best,alts):
 img=Image.new('RGB',(W,1160),BG);d=ImageDraw.Draw(img);accent=GOLD
 d.rounded_rectangle((24,20,1056,112),24,fill=PANEL,outline=accent,width=2);d.text((52,36),'GOOL BEST BET',font=_font(36,True),fill=accent);d.text((52,79),'ONE MATCH • ONE BEST MARKET',font=_font(15,True),fill=TEXT);d.rounded_rectangle((840,38,1028,93),16,outline=GREEN,width=2);d.text((882,53),'ENTRY',font=_font(20,True),fill=GREEN)
 _center(d,f'{m.home} — {m.away}',160,_fit(d,f'{m.home} — {m.away}',920,34,True),TEXT);_center(d,f"LIVE {int(getattr(m,'minute',0) or 0)}'  •  {int(getattr(m,'home_score',0) or 0)} : {int(getattr(m,'away_score',0) or 0)}",210,_font(28,True),CYAN)
 d.rounded_rectangle((55,275,1025,490),28,fill=PANEL2,outline=GOLD,width=3);_center(d,'ЛУЧШАЯ СТАВКА',305,_font(21,True),MUTED);_center(d,best['name'],350,_fit(d,best['name'],850,48,True),TEXT);_center(d,f"КЭФ {best['odd']:.2f}",414,_font(36,True),GOLD);_center(d,'✓ ВХОД: ДА',458,_font(22,True),GREEN)
 _box(d,55,535,225,118,'MODEL',f"{best['confidence']:.0f}/100");_box(d,295,535,225,118,'MARKET',f"{best['market_score']:.0f}/100");_box(d,535,535,225,118,'VALUE',f"{best['edge']:+.1f} п.п.",GREEN if best['edge']>0 else RED);_box(d,775,535,250,118,'CONTEXT',f"{best['context']:.0f}/100")
 d.rounded_rectangle((55,685,1025,825),24,fill=PANEL,outline=GOLD,width=2);d.text((85,708),'MASTER SCORE',font=_font(18,True),fill=MUTED);d.text((85,750),f"{best['score']:.0f}/100",font=_font(48,True),fill=GOLD);d.text((350,720),'Рынок подтверждён' if best['status'] not in {'CONFLICT','DISAGREE'} else 'Конфликт рынка',font=_font(23,True),fill=GREEN if best['status'] not in {'CONFLICT','DISAGREE'} else RED);d.text((350,762),best['status'],font=_font(19,True),fill=TEXT)
 if alts:d.rounded_rectangle((55,855,1025,970),20,fill=PANEL,outline=LINE,width=2);d.text((85,880),'БЛИЖАЙШИЙ КАНДИДАТ',font=_font(16,True),fill=MUTED);d.text((85,920),f"{alts[0]['name']} @ {alts[0]['odd']:.2f}  •  {alts[0]['score']:.0f}/100",font=_fit(d,f"{alts[0]['name']} @ {alts[0]['odd']:.2f}  •  {alts[0]['score']:.0f}/100",850,25,True),fill=TEXT)
 _center(d,'GOOL AI • BEST BET ENGINE',1080,_font(19,True),MUTED);o=BytesIO();img.save(o,'PNG',optimize=True);return o.getvalue()
def render_result(row,result,final_score,pnl):
 win=result=='win';push=result=='push';accent=GREEN if win else GOLD if push else RED;title='✓ СТАВКА ЗАШЛА' if win else '↩ ВОЗВРАТ' if push else '✕ СТАВКА НЕ ЗАШЛА';p=row.get('primary') or {};label=p.get('label') or p.get('market') or 'BEST BET';odd=float(p.get('odd') or 0)
 img=Image.new('RGB',(W,900),BG);d=ImageDraw.Draw(img);d.rounded_rectangle((24,20,1056,112),24,fill=PANEL,outline=accent,width=2);d.text((52,36),'GOOL BEST BET',font=_font(36,True),fill=accent);d.text((52,79),'RESULT CARD',font=_font(15,True),fill=TEXT)
 _center(d,title,165,_font(43,True),accent);_center(d,f"{row.get('home','?')} — {row.get('away','?')}",235,_fit(d,f"{row.get('home','?')} — {row.get('away','?')}",900,31,True),TEXT);_center(d,f'ФИНАЛ {final_score}',282,_font(28,True),CYAN)
 d.rounded_rectangle((55,350,1025,535),26,fill=PANEL2,outline=accent,width=3);_center(d,str(label),382,_fit(d,label,850,42,True),TEXT);_center(d,f'КЭФ {odd:.2f}',438,_font(31,True),GOLD);_center(d,f"Вход: {row.get('minute',0)}' • {row.get('score_at_signal','—')}",485,_font(20,True),MUTED)
 _box(d,55,585,290,120,'MASTER НА ВХОДЕ',f"{float(row.get('master') or 0):.0f}/100");_box(d,365,585,290,120,'РЕЗУЛЬТАТ',title.replace('✓ ','').replace('✕ ','').replace('↩ ',''),accent);_box(d,675,585,350,120,'PNL',f'{pnl:+.2f} units',accent)
 _center(d,'GOOL AI • VERIFIED BET RESULT',820,_font(19,True),MUTED);o=BytesIO();img.save(o,'PNG',optimize=True);return o.getvalue()
