"""Truthful GOOL CORE card presentation for LIVE-only pricing.

Never presents a missing/stale quote as a current price. Bovada/prematch wording is
removed from the card; sporting evidence remains visible even when live odds are absent.
"""
from __future__ import annotations
from io import BytesIO
from PIL import Image, ImageDraw
import signal_card as sc

_orig_render = sc.render_signal_card


def _has_live_price(row):
    if not isinstance(row, dict):
        return False
    if str(row.get("live_odds_status") or "").upper() == "UNAVAILABLE":
        return False
    try:
        return float(row.get("odd") or 0) > 1.001 and bool(row.get("quote_ts"))
    except Exception:
        return False


def _sources(row):
    if not _has_live_price(row):
        return "LIVE КЭФ НЕДОСТУПЕН • АНАЛИТИЧЕСКИЙ СИГНАЛ"
    prices=[]
    for x in row.get("source_prices") or []:
        src=str(x.get("source") or "LIVE")
        if "bovada" in src.lower():
            continue
        try: prices.append(f"{src} {float(x.get('odd')):.2f}")
        except Exception: pass
    if prices:
        return "  •  ".join(prices[:3])
    try:
        src=str(row.get("source") or "LIVE")
        if "bovada" in src.lower():
            return "LIVE КЭФ НЕДОСТУПЕН • АНАЛИТИЧЕСКИЙ СИГНАЛ"
        return f"{src} {float(row.get('odd')):.2f}"
    except Exception:
        return "LIVE КЭФ НЕДОСТУПЕН • АНАЛИТИЧЕСКИЙ СИГНАЛ"


def _movement(row):
    if not _has_live_price(row):
        return "LIVE ЦЕНА НЕ ПОДТВЕРЖДЕНА", sc.MUTED
    return _orig_movement(row)


def _reason(pressure, rows, probs):
    base=_orig_reason(pressure, rows, probs)
    best=sc._best(rows or [])
    if not _has_live_price(best):
        # No edge/price language is allowed without a verified current quote.
        parts=[p.strip() for p in base.split(".") if p.strip()]
        parts=[p for p in parts if "edge" not in p.lower() and "цена подтверждена" not in p.lower()]
        if not parts:
            parts=["LIVE-статистика, модель и профиль матча подтверждают спортивный сигнал"]
        parts.append("Текущий LIVE-кэф не подтверждён и в оценку входа не подставляется")
        return ". ".join(parts[:3])+"."
    return base


_orig_sources=sc._sources
_orig_movement=sc._movement
_orig_reason=sc._reason
sc._sources=_sources
sc._movement=_movement
sc._reason=_reason


def render_signal_card(*args, **kwargs):
    raw=_orig_render(*args, **kwargs)
    kind=kwargs.get("kind", "entry")
    if len(args) >= 4:
        kind=args[3]
    if kind != "entry":
        return raw
    img=Image.open(BytesIO(raw)).convert("RGB")
    d=ImageDraw.Draw(img)
    # Replace legacy source legend (which mentioned Bovada) with actual architecture.
    d.rectangle((70,1138,1015,1178), fill=sc.PANEL)
    d.text((85,1152),"Flashscore/LSApp • Kambi/BetRivers • xG/xGoT • LIVE stats • Market Movement",font=sc._font(14),fill=sc.MUTED)
    out=BytesIO();img.save(out,"PNG",optimize=True);return out.getvalue()

sc.render_signal_card=render_signal_card
