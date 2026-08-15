"""Telegram output filter for GOOL LIVE.

Keep the full LIVE engine, XG layer and internal tracking/logging unchanged, but
send only two user-facing event types:
1) actionable ENTRY/STRONG signals (including post-goal re-entry);
2) goal confirmations for previously sent/tracked signals.

OBSERVE, SILENT, ordinary follow-ups, halftime observations and weakening
updates stay in logs and are not sent to Telegram.
"""
from __future__ import annotations

import logging

import live_candidate_patch as lc

logger = logging.getLogger("telegram_signal_filter_patch")

_orig_format = lc._format_strategy_signal
_orig_send = lc._send

# IMPORTANT: the formatter normalizes ENTRY/STRONG/re-entry actions to
# "МОЖНО ЗАХОДИТЬ".  Keep that exact marker here; previously the filter only
# allowed "СИГНАЛ — МОЖНО ЗАХОДИТЬ", so every valid CORE entry was suppressed.
_ALLOWED_MARKERS = (
    "МОЖНО ЗАХОДИТЬ",
    "СИГНАЛ ЗАШЁЛ",
)


def _format_strategy_signal(m, p, s, recs, goals, reason, route, master, hz, market):
    grade = lc._signal_grade(master)

    # No chat noise: ordinary updates never reach Telegram.
    if reason == "followup":
        logger.info(
            "TELEGRAM_SUPPRESS followup %d' %s — %s | grade=%s master=%.0f",
            int(getattr(m, "minute", 0) or 0), getattr(m, "home", ""),
            getattr(m, "away", ""), grade, float(master or 0),
        )
        return ""

    # A brand-new signal is user-facing only when it is actionable.
    if reason == "signal" and grade not in {"ENTRY", "STRONG"}:
        logger.info(
            "TELEGRAM_SUPPRESS %s %d' %s — %s | grade=%s master=%.0f",
            reason, int(getattr(m, "minute", 0) or 0), getattr(m, "home", ""),
            getattr(m, "away", ""), grade, float(master or 0),
        )
        return ""

    text = _orig_format(m, p, s, recs, goals, reason, route, master, hz, market)

    if reason in {"signal", "reentry"}:
        replacements = (
            ("🔴 <b>LIVE-СИГНАЛ</b>", "🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>"),
            ("🔵 <b>ПРОГНОЗ НА 2-Й ТАЙМ</b>", "🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>"),
            ("♻️ <b>НОВЫЙ ВХОД ПОСЛЕ ГОЛА</b>", "🔥 <b>СИГНАЛ — МОЖНО ЗАХОДИТЬ</b>"),
            ("🟡 <b>МОЖНО РАССМАТРИВАТЬ ВХОД</b>", "🔥 <b>МОЖНО ЗАХОДИТЬ</b>"),
            ("🔥 <b>МОЖНО ЗАХОДИТЬ — СИЛЬНЫЙ СИГНАЛ</b>", "🔥 <b>МОЖНО ЗАХОДИТЬ</b>"),
            ("🔥 <b>СТАТИСТИКА ПОСЛЕ ГОЛА СНОВА ПОДТВЕРЖДАЕТ ВХОД</b>", "🔥 <b>МОЖНО ЗАХОДИТЬ</b>"),
        )
        for old, new in replacements:
            text = text.replace(old, new)

    elif reason == "goal":
        text = text.replace("✅ <b>ГОЛ — СИГНАЛ СРАБОТАЛ!</b>", "✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>")
        text = text.replace("✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>\n🔄 Матч и LIVE-линии пересчитаны", "✅ <b>СИГНАЛ ЗАШЁЛ — ГОЛ!</b>")

    return text


def _send(m, p, recs, text):
    if not text or not any(marker in text for marker in _ALLOWED_MARKERS):
        logger.info(
            "TELEGRAM_SUPPRESS non-actionable %d' %s — %s",
            int(getattr(m, "minute", 0) or 0), getattr(m, "home", ""), getattr(m, "away", ""),
        )
        return False
    logger.info(
        "TELEGRAM_ALLOW actionable %d' %s — %s",
        int(getattr(m, "minute", 0) or 0), getattr(m, "home", ""), getattr(m, "away", ""),
    )
    return _orig_send(m, p, recs, text)


lc._format_strategy_signal = _format_strategy_signal
lc._send = _send
