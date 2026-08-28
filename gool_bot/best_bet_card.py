"""Compact PNG cards for GOOL BEST BET."""
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
W=1080;BG=(5,10,18);PANEL=(13,22,36);TEXT=(247,249,252);MUTED=(151,166,188);GOLD=(255,184,48);GREEN=(82,220,118);RED=(244,104,104);CYAN=(61,178,255)
def _font(s,b=False):
 for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if b else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if b else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']:
  try:return ImageFont.truetype(p,s)
  except OSError:pass
 return ImageFont.load_default()
def _center(d,t,y,f,c):
 b=d.textbbox((0,0),str(t),font=f);d.text(((W-(b[2]-b[0]))/2,y),str(t),font=f,fill=c)
def render_entry(m,best,alts):
 img=Image.new('RGB',(W,850),BG);d=ImageDraw.Draw(img);d.rounded_rectangle((25,20,1055,110),24,fill=PANEL,outline=GOLD,width=2);d.text((55,38),'GOOL BEST BET',font=_font(36,True),fill=GOLD);_center(d,f'{m.home} — {m.away}',160,_font(31,True),TEXT);_center(d,f"LIVE {int(getattr(m,'minute',0) or 0)}' • {int(getattr(m,'home_score',0) or 0)}:{int(getattr(m,'away_score',0) or 0)}",210,_font(27,True),CYAN);_center(d,best['name'],310,_font(43,True),TEXT);_center(d,f"КЭФ {best['odd']:.2f}",370,_font(35,True),GOLD);_center(d,f"MASTER {best['score']:.0f}/100 • MODEL {best['confidence']:.0f} • VALUE {best['edge']:+.1f} п.п.",470,_font(25,True),GREEN);_center(d,f"MARKET {best['status']} • FLOW {best['market_score']:.0f}",530,_font(22,True),TEXT);_center(d,'✓ ВХОД: ДА',640,_font(34,True),GREEN);_center(d,'GOOL AI • ONE MATCH • ONE BEST MARKET',780,_font(18,True),MUTED);o=BytesIO();img.save(o,'PNG',optimize=True);return o.getvalue()
def render_result(row,result,final_score,pnl):
 accent=GREEN if result=='win' else GOLD if result=='push' else RED;title='✓ СТАВКА ЗАШЛА' if result=='win' else '↩ ВОЗВРАТ' if result=='push' else '✕ СТАВКА НЕ ЗАШЛА';p=row.get('primary') or {};img=Image.new('RGB',(W,720),BG);d=ImageDraw.Draw(img);_center(d,'GOOL BEST BET',55,_font(36,True),accent);_center(d,title,150,_font(43,True),accent);_center(d,f"{row.get('home','?')} — {row.get('away','?')}",235,_font(30,True),TEXT);_center(d,f'ФИНАЛ {final_score}',285,_font(28,True),CYAN);_center(d,str(p.get('label') or p.get('market') or 'BEST BET'),380,_font(35,True),TEXT);_center(d,f"КЭФ {float(p.get('odd') or 0):.2f} • PNL {pnl:+.2f} units",450,_font(27,True),accent);_center(d,'GOOL AI • VERIFIED BET RESULT',650,_font(18,True),MUTED);o=BytesIO();img.save(o,'PNG',optimize=True);return o.getvalue()
