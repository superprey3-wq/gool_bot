"""Ensure GOOL cards display the actual production source hierarchy."""
from __future__ import annotations
from io import BytesIO
from PIL import Image,ImageDraw
import signal_card

_orig=signal_card.render_signal_card

def render_signal_card(*args,**kwargs):
    raw=_orig(*args,**kwargs);img=Image.open(BytesIO(raw)).convert("RGB");d=ImageDraw.Draw(img);h=img.height
    d.rectangle((0,h-72,img.width,h),fill=signal_card.BG)
    text="FLASHSCORE/LSAPP PRIMARY • KAMBI CONFIRM • SGO OPTIONAL"
    font=signal_card._font(18,True);box=d.textbbox((0,0),text,font=font);d.text(((img.width-(box[2]-box[0]))/2,h-47),text,font=font,fill=signal_card.MUTED)
    out=BytesIO();img.save(out,"PNG",optimize=True);return out.getvalue()

signal_card.render_signal_card=render_signal_card
