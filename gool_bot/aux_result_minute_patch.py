"""Show the actual event minute on auxiliary result cards.

FIRST_HALF_GOAL wins must display the minute when the post-entry goal was
observed (for example 34'), not a hard-coded HT label. Period-end labels remain
only for losses settled at the end of the relevant period.
"""
from __future__ import annotations

from io import BytesIO
import logging

from PIL import Image, ImageDraw

import multi_engine_card as mec

logger = logging.getLogger("aux_result_minute")


def _result_time_label(match, engine: str, result) -> str:
    is_win = str(result).lower() == "win"
    try:
        minute = int(getattr(match, "minute", 0) or 0)
    except Exception:
        minute = 0

    # A confirmed goal belongs to the actual LIVE minute. Never replace a
    # first-half goal at 19'/34'/44' with the generic HT label.
    if is_win and minute > 0:
        return f"{minute}'"

    if engine == "first_half_goal":
        return "HT"
    if engine == "second_half_over15":
        return "FT"
    return f"{minute}'" if minute > 0 else "—"


def render_result_card(match, engine, result, market=None, odd=None):
    accent, title, _, mode = mec._header_text(engine)
    W, H = 1200, 800
    img = Image.new("RGBA", (W, H), mec.BG + (255,))
    d = ImageDraw.Draw(img)
    mec.panel(img, (24, 20, W - 24, H - 22), accent, 32, 3)
    d = ImageDraw.Draw(img)
    d.text((55, 42), title, font=mec.F(34, True), fill=mec.WHITE)
    d.rounded_rectangle((1000, 40, 1140, 95), 15, outline=accent, width=2)
    d.text((1035, 54), mode, font=mec.F(20, True), fill=accent)

    is_win = str(result).lower() == "win"
    headline = "СИГНАЛ ПОДТВЕРЖДЁН" if is_win else "СИГНАЛ НЕ ПОДТВЕРЖДЁН"
    mec.center(d, headline, 120, mec.fit(d, headline, 1000, 52, True), mec.GREEN if is_win else mec.RED, W)

    hn, an = mec.logos(getattr(match, "event_id", ""))
    mec.crest(img, mec.dl(hn), 190, 380, accent, 165)
    mec.crest(img, mec.dl(an), 1010, 380, accent, 165)
    mec.panel(img, (425, 287, 775, 472), accent, 28, 2)
    d = ImageDraw.Draw(img)
    mec.center(d, f"{match.home_score} : {match.away_score}", 325, mec.F(72, True), mec.WHITE, W)
    mec.center(d, _result_time_label(match, engine, result), 408, mec.F(30, True), accent, W)

    mec.center(d, mec._signal_label(engine), 545, mec.fit(d, mec._signal_label(engine), 950, 30, True), mec.WHITE, W)
    mec.center(d, "Результат относится к футбольному прогнозу, не к коэффициенту", 620, mec.F(21), mec.MUTED, W)
    mec.center(d, "GOOL AI 2.0 • STRATEGY ANALYTICS", 735, mec.F(19, True), mec.MUTED, W)

    out = BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


mec.render_result_card = render_result_card
logger.info("Aux result minute patch active | wins show actual LIVE minute; HT/FT reserved for period-end losses")
