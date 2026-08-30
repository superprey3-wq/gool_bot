from __future__ import annotations
from io import BytesIO
from PIL import Image,ImageDraw,ImageFont

BG=(6,10,18);PANEL=(14,22,34);WHITE=(245,248,252);MUTED=(155,169,190);ACC=(55,180,255);GREEN=(75,220,120);RED=(245,90,90)

def F(n,b=False):
    for p in (("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if b else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),):
        try:return ImageFont.truetype(p,n)
        except:pass
    return ImageFont.load_default()

def _fit(d,t,w,n=40):
    for s in range(n,17,-2):
        f=F(s,True)
        if d.textbbox((0,0),str(t),font=f)[2]<=w:return f
    return F(18,True)

def render(match,period,dec,bet,result=None):
    W,H=1200,1050
    img=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(img)
    d.rounded_rectangle((24,24,W-24,H-24),30,fill=PANEL,outline=ACC,width=3)
    mode={"FULL_TIME":"ВЕСЬ МАТЧ","FIRST_HALF":"1-Й ТАЙМ","SECOND_HALF":"2-Й ТАЙМ"}.get(period,period)
    headline="GOOL AI • ТОЧНЫЙ TOTAL" if result is None else ("GOOL AI • WIN" if result=="win" else "GOOL AI • PUSH" if result=="push" else "GOOL AI • LOSS")
    d.text((60,52),headline,font=F(34,True),fill=WHITE)
    d.text((60,103),mode,font=F(24,True),fill=ACC)
    teams=f"{match.home} — {match.away}"
    d.text((60,165),teams,font=_fit(d,teams,1080,38),fill=WHITE)
    d.text((60,220),f"{match.minute}'   СЧЁТ {match.home_score}:{match.away_score}",font=F(30,True),fill=WHITE)
    side="ТБ" if bet.get("side")=="OVER" else "ТМ"
    line=bet.get("line");odd=bet.get("odd")
    pick=f"{side} {line:g}" if isinstance(line,(int,float)) else side
    if odd:pick+=f"  @ {float(odd):.2f}"
    d.rounded_rectangle((55,292,1145,455),24,fill=(9,17,29),outline=GREEN if result in (None,"win") else RED,width=2)
    d.text((88,318),"СТАВКА",font=F(20,True),fill=MUTED)
    d.text((88,355),pick,font=_fit(d,pick,760,48),fill=GREEN if result in (None,"win") else RED)
    prob=float(bet.get("model_probability",0) or 0);fair=bet.get("fair_odd");value=bet.get("value_edge")
    d.text((830,323),"MODEL",font=F(18,True),fill=MUTED);d.text((830,357),f"{prob:.1f}%",font=F(40,True),fill=WHITE)
    boxes=[("POTENTIAL",f"{dec.potential:.0f}/100"),("LIVE THREAT",f"{dec.threat:.0f}/100"),("GOAL 10M",f"{dec.p_goal_10m:.1f}%"),("λ ОСТАЛОСЬ",f"{dec.lambda_remaining:.2f}"),("FAIR",f"{fair:.2f}" if fair else "—"),("VALUE",f"+{float(value):.1f} п.п." if value is not None else "—")]
    x0,y0=55,515;cw=345;ch=112;gap=27
    for i,(lab,val) in enumerate(boxes):
        r=i//3;c=i%3;x=x0+c*(cw+gap);y=y0+r*(ch+22)
        d.rounded_rectangle((x,y,x+cw,y+ch),18,fill=(9,17,29),outline=(45,62,84),width=1)
        d.text((x+18,y+16),lab,font=F(17,True),fill=MUTED);d.text((x+18,y+50),val,font=_fit(d,val,cw-36,28),fill=WHITE)
    reason=f"P(0) {dec.p0:.1f}% • P(1) {dec.p1:.1f}% • P(2+) {dec.p2plus:.1f}%"
    d.text((60,805),reason,font=F(23,True),fill=WHITE)
    d.text((60,852),str(dec.reason)[:105],font=F(18),fill=MUTED)
    src=str(bet.get("source") or "MODEL ONLY")
    d.text((60,942),f"Источник коэффициента: {src}",font=F(18),fill=MUTED)
    d.text((60,982),"GOOL • FULL MATCH / 1H / 2H • OVER / UNDER / NO BET",font=F(17,True),fill=MUTED)
    out=BytesIO();img.save(out,"PNG",optimize=True);return out.getvalue()
