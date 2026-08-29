"""Compact PNG card renderer for Monkey strong PROGRUZ signals."""
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont
W=1080;BG=(5,10,18);PANEL=(13,22,36);TEXT=(247,249,252);MUTED=(151,166,188);ORANGE=(255,132,35);GREEN=(82,220,118);CYAN=(61,178,255);RED=(244,104,104)
def _font(s,b=False):
 for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if b else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if b else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']:
  try:return ImageFont.truetype(p,s)
  except OSError:pass
 return ImageFont.load_default()
def _center(d,t,y,f,c):
 b=d.textbbox((0,0),str(t),font=f);d.text(((W-(b[2]-b[0]))/2,y),str(t),font=f,fill=c)
def _period(scope):
 s=str(scope or 'FULL_TIME').upper();return '1-Й ТАЙМ' if s=='FIRST_HALF' else '2-Й ТАЙМ' if s=='SECOND_HALF' else 'ВЕСЬ МАТЧ'
def _pick(x):
 side='ТБ' if str(x.get('side') or '').upper()=='OVER' else 'ТМ';line=x.get('line');odd=float(x.get('odd') or 0);return f"{side} {float(line):g} @ {odd:.2f}" if line not in (None,'') else f"{side} @ {odd:.2f}"
def _live_stats(x):
 st=x.get('live_stats') if isinstance(x.get('live_stats'),dict) else {};p=float(x.get('live_pressure',0) or 0);m=float(x.get('live_momentum',0) or 0)
 def total(k):
  v=st.get(k)
  try:return float(v[0])+float(v[1])
  except Exception:return 0.0
 return p,m,total('xg'),total('shots_on_target'),total('big_chances')
def render(x):
 img=Image.new('RGB',(W,900),BG);d=ImageDraw.Draw(img)
 d.rounded_rectangle((25,20,1055,112),24,fill=PANEL,outline=ORANGE,width=2);d.text((55,40),'GOOL STRONG PROGRUZ',font=_font(34,True),fill=ORANGE)
 _center(d,f"{x.get('home','')} — {x.get('away','')}",155,_font(31,True),TEXT)
 score=str(x.get('score_live') or x.get('score') or '?:?');minute=x.get('minute');_center(d,f"LIVE {minute}' • {score}",210,_font(28,True),CYAN)
 _center(d,_period(x.get('scope')),270,_font(23,True),MUTED)
 _center(d,_pick(x),335,_font(48,True),TEXT)
 move=float(x.get('median_delta_pct',0) or 0);strength=float(x.get('strength',0) or 0);books=int(x.get('books',0) or 0)
 _center(d,f"ДВИЖЕНИЕ {move:.1f}% • ПОДТВЕРЖДЕНИЙ {books}",425,_font(27,True),ORANGE)
 _center(d,f"СИЛА {strength:.0f}/100",480,_font(32,True),GREEN)
 p,m,xg,sot,big=_live_stats(x);d.rounded_rectangle((70,565,1010,730),24,fill=PANEL)
 _center(d,f"LIVE PRESSURE {p:.0f} • MOMENTUM {m:.0f}",595,_font(25,True),CYAN)
 _center(d,f"xG {xg:.2f} • SOT {sot:.0f} • BIG CHANCES {big:.0f}",650,_font(23,True),TEXT)
 verdict='РЫНОК + LIVE ПОДТВЕРЖДЕНЫ' if strength>=80 else 'LIVE MARKET FLOW';_center(d,verdict,775,_font(28,True),GREEN)
 _center(d,'GOOL AI • FLASH TRUTH • MARKET FLOW',850,_font(18,True),MUTED)
 o=BytesIO();img.save(o,'PNG',optimize=True);return o.getvalue()
