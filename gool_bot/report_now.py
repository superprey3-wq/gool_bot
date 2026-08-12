"""Build an on-demand snapshot of today's GOOL BOT signal journal."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from live_engine import fetch_summary
from daily_report import _score_from_summary, _market_goals, _settle_total
from signal_journal import all_signals

MOSCOW = ZoneInfo("Europe/Moscow")


def _today_rows():
    today = datetime.now(MOSCOW).date().isoformat()
    rows = []
    for row in all_signals():
        try:
            created = datetime.fromtimestamp(int(row.get("created_ts", 0)), MOSCOW)
        except Exception:
            continue
        if created.date().isoformat() == today:
            rows.append(row)
    return rows


def _live_signal_rows(rows):
    """Only real signal cycles count in statistics.

    followup = informational update of an existing signal and must not inflate the
    number of bets/signals. A goal row is a fresh signal cycle only when the bot
    continued tracking after that goal (<= 80').
    """
    result = []
    for row in rows:
        if row.get("kind") != "live":
            continue
        reason = str(row.get("reason") or "signal")
        if reason == "followup":
            continue
        if reason == "goal":
            try:
                minute = int(row.get("minute") or 0)
            except Exception:
                minute = 0
            # A late goal closes tracking; it is the success of the preceding
            # signal, not a new entry after 80'.
            if minute > 80:
                continue
        result.append(row)
    return result


def build_report_text() -> str:
    rows = _today_rows()
    live_rows = _live_signal_rows(rows)
    pre_rows = [r for r in rows if r.get("kind") == "prematch"]

    live_ok = 0
    live_wait = 0
    live_details = []
    for row in live_rows:
        body = fetch_summary(str(row.get("event_id", "")))
        if not body:
            live_wait += 1
            continue
        fh, fa, _, _ = _score_from_summary(body)
        try:
            sh, sa = map(int, str(row.get("score_at_signal", "0:0")).split(":"))
        except Exception:
            sh = sa = 0
        hit = (fh + fa) > (sh + sa)
        if hit:
            live_ok += 1
            mark = "✅"
        else:
            live_wait += 1
            mark = "⏳"
        live_details.append(
            f"{mark} {row.get('home')} — {row.get('away')} | "
            f"{row.get('minute')}' {row.get('score_at_signal')} → {fh}:{fa}"
        )

    pre_ok = pre_bad = pre_wait = 0
    pre_details = []
    for row in pre_rows:
        body = fetch_summary(str(row.get("event_id", "")))
        if not body:
            pre_wait += 1
            continue
        fh, fa, hh, ha = _score_from_summary(body)
        goals = _market_goals(str(row.get("scope", "Матч")), fh, fa, hh, ha)
        try:
            res = _settle_total(str(row.get("side", "ТБ")), float(row.get("line", 0)), goals)
        except Exception:
            pre_wait += 1
            continue
        if res in {"+", "+½"}:
            pre_ok += 1; mark = "✅"
        elif res in {"-", "-½"}:
            pre_bad += 1; mark = "❌"
        else:
            pre_wait += 1; mark = "⏳"
        pre_details.append(
            f"{mark} {row.get('home')} — {row.get('away')} | "
            f"{row.get('scope')} {row.get('side')} {row.get('line')} → {fh}:{fa}"
        )

    lines = [
        "📊 <b>GOOL BOT — ОТЧЁТ НА СЕЙЧАС</b>",
        f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}",
        "",
        "🔴 <b>LIVE</b>",
        f"Реальных сигналов: <b>{len(live_rows)}</b>",
        f"✅ Уже дали следующий гол: <b>{live_ok}</b>",
        f"⏳ Ещё не закрыты: <b>{live_wait}</b>",
        "ℹ️ Повторные обновления матча в число сигналов не входят.",
    ]
    if live_rows:
        lines.append(f"🎯 Текущая доля с голом: <b>{round(live_ok / len(live_rows) * 100)}%</b>")
    lines += [
        "",
        "🔥 <b>ПРЕМАТЧ</b>",
        f"Всего сигналов: <b>{len(pre_rows)}</b>",
        f"✅ Сейчас проходят: <b>{pre_ok}</b>",
        f"❌ Сейчас не проходят: <b>{pre_bad}</b>",
        f"⏳ Нет данных/возврат: <b>{pre_wait}</b>",
    ]
    if live_details:
        lines += ["", "<b>Последние LIVE-сигналы:</b>"] + live_details[-12:]
    if pre_details:
        lines += ["", "<b>Последние прематч:</b>"] + pre_details[-10:]
    if not rows:
        lines += ["", "Сегодня в журнале пока нет сигналов."]
    return "\n".join(lines)
