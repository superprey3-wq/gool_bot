"""Render the private BetB2B movement dot on 1T/2T signal cards only."""
from __future__ import annotations
from io import BytesIO
import logging
from PIL import Image, ImageDraw
import multi_engine_runtime as runtime
import betb2b_market_signal as bms

logger = logging.getLogger("betb2b_card_patch")
_orig = runtime.render_engine_card
GREEN=(82,220,118); RED=(244,104,104); YELLOW=(245,197,66); WHITE=(247,249,252)


def _render(match, engine, score=0, delta=None, odd=None, result=None):
    png = _orig(match, engine, score, delta, odd, result)
    if result is not None or not png:
        return png
    try:
        dot = bms.dot_for_match(match.home, match.away)
        col = GREEN if dot == "🟢" else RED if dot == "🔴" else YELLOW
        im = Image.open(BytesIO(png)).convert("RGB")
        d = ImageDraw.Draw(im)
        # Top-right private status lamp. No text/legend is exposed on the card.
        d.ellipse((1110, 58, 1138, 86), fill=col, outline=WHITE, width=1)
        out = BytesIO(); im.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:
        logger.exception("BETB2B_AUX_DOT_RENDER_FAIL")
        return png


runtime.render_engine_card = _render
logger.info("BETB2B private market dot active on 1T/2T signal cards")
