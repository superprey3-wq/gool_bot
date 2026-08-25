"""Harden CORE ENTRY card delivery without losing actionable signals.

PNG remains preferred. Text fallback is used only after render/upload retries fail,
and every fallback records an explicit reason in production logs.
"""
from __future__ import annotations
import logging
import time
import requests
import telegram_image_signal_patch as tip

logger = logging.getLogger("entry_card_delivery")


def _send_photo_all(match, pressure, recs, kind, master=None):
    token = tip.unified_bot.BOT_TOKEN
    recipients = tip.get_subscribers()
    if not token or not recipients:
        logger.error("CARD_DELIVERY_NO_TARGET event=%s token=%s recipients=%d", getattr(match,"event_id",""), bool(token), len(recipients))
        return False

    xg = tip.gx._cached(match) if kind == "entry" else None
    probs = tip._display_probabilities(match, master, xg) if kind == "entry" else None
    png = None
    render_error = None
    for attempt in range(2):
        try:
            png = tip.render_signal_card(match, pressure, recs, kind=kind, master=master, probabilities=probs)
            if png and len(png) > 1000:
                logger.info("CARD_RENDER_OK event=%s kind=%s bytes=%d attempt=%d", getattr(match,"event_id",""), kind, len(png), attempt+1)
                break
            render_error = f"empty_or_small_png:{len(png or b'')}"
            png = None
        except Exception as exc:
            render_error = f"{type(exc).__name__}: {exc}"
            logger.exception("CARD_RENDER_FAIL event=%s kind=%s attempt=%d", getattr(match,"event_id",""), kind, attempt+1)
        if attempt == 0:
            time.sleep(0.4)

    primary = (recs or [None])[0]
    caption = "🔥 GOOL AI • МОЖНО ЗАХОДИТЬ" if kind == "entry" else f"✅ GOOL AI • СТАВКА ЗАШЛА • {tip._primary_label(primary)}"
    fallback = tip._compact_fallback(match, recs, kind, master, xg)
    delivered = 0
    archived = False

    for chat_id in recipients:
        photo_ok = False
        upload_error = None
        if png:
            for attempt in range(3):
                try:
                    r = requests.post(
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        data={"chat_id":str(chat_id), "caption":caption},
                        files={"photo":("gool-signal.png", png, "image/png")},
                        timeout=30,
                    )
                    photo_ok = r.ok
                    if photo_ok:
                        logger.info("CARD_PHOTO_SENT event=%s kind=%s chat=%s attempt=%d", getattr(match,"event_id",""), kind, chat_id, attempt+1)
                        if kind == "entry" and not archived:
                            try:
                                photos = ((r.json().get("result") or {}).get("photo") or [])
                                file_id = (photos[-1] or {}).get("file_id") if photos else None
                                if file_id:
                                    tip.save_entry_card(getattr(match,"event_id",""), file_id, caption)
                                    archived = True
                            except Exception:
                                logger.exception("CARD_ARCHIVE_FAIL event=%s", getattr(match,"event_id",""))
                        break
                    upload_error = f"HTTP {r.status_code}: {r.text[:500]}"
                    logger.warning("CARD_UPLOAD_FAIL event=%s kind=%s chat=%s attempt=%d %s", getattr(match,"event_id",""), kind, chat_id, attempt+1, upload_error)
                except requests.RequestException as exc:
                    upload_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("CARD_UPLOAD_FAIL event=%s kind=%s chat=%s attempt=%d %s", getattr(match,"event_id",""), kind, chat_id, attempt+1, upload_error)
                if attempt < 2:
                    time.sleep(1.0 + attempt)

        if photo_ok:
            delivered += 1
            continue

        reason = render_error if not png else upload_error or "unknown_upload_failure"
        logger.error("CARD_TEXT_FALLBACK event=%s kind=%s chat=%s reason=%s", getattr(match,"event_id",""), kind, chat_id, reason)
        if tip._send_text_to_chat(token, chat_id, fallback):
            delivered += 1

    return delivered > 0


tip._send_photo_all = _send_photo_all
logger.info("ENTRY card delivery patch active | render retry=2 | Telegram photo retry=3 | explicit fallback diagnostics")
