"""Build an on-demand snapshot of today's GOOL BOT signal journal."""
from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from live_engine import discover_live_matches, fetch_summary
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
            if minute > 80:
                continue
        result.append(row)
    return result


def _current_live_ids() -> set[str]:
    try:
        matches = asyncio.run(discover_live_matches())
    except Exception:
        return set()
    return {str(m.event_id) for m in matches}


def build_report_text() -> str:
    rows = _today_rows()
    live_rows = _live_signal_rows(rows)
    pre_rows = [r for r in rows if r.get("kind") == "prematch"]
    current_live_ids = _current_live_ids()

    summary_cache: dict[str, str | None] = {}

    def get_summary(event_id: str):
        event_id = str(event_id or "")
        if not event_id:
            return None
        if event_id not in summary_cache:
            try:
                summary_cache[event_id] = fetch_summary(event_id)
            except Exception:
                summary_cache[event_id] = None
        return summary_cache[event_id]

    live_ok = live_bad = live_wait = 0
    live_details = []
    for row in live_rows:
        event_id = str(row.get("event_id", ""))
        body = get_summary(event_id)
        if not body:
            live_wait += 1
            continue
        try:
            fh, fa, _, _ = _score_from_summary(body)
        except Exception:
            live_wait += 1
            continue
        try:
            sh, sa = map(int, str(row.get("score_at_signal", "0:0")).split(":"))
        except Exception:
            sh = sa = 0
        hit = (fh + fa) > (sh + sa)
        if hit:
            live_ok += 1
            mark = "✅"
        elif event_id in current_live_ids:
            live_wait += 1
            mark = "⏳"
        else:
            live_bad += 1
            mark = "❌"
        live_details.append(
            f"{mark} {row.get('home')} — {row.get('away')} | "
            f"{row.get('minute')}' {row.get('score_at_signal')} → {fh}:{fa}"
        )

    pre_ok = pre_bad = pre_wait = 0
    pre_details = []
    for row in pre_rows:
        body = get_summary(str(row.get("event_id", "")))
        if not body:
            pre_wait += 1
            continue
        try:
            fh, fa, hh, ha = _score_from_summary(body)
            goals = _market_goals(str(row.get("scope", "Матч")), fh, fa, hh, ha)
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

    settled = live_ok + live_bad
    live_rate = round(live_ok / settled * 100) if settled else 0
    lines = [
        "📊 <b>GOOL BOT — ОТЧЁТ НА СЕЙЧАС</b>",
        f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}",
        "",
        "🔴 <b>LIVE</b>",
        f"Реальных сигналов: <b>{len(live_rows)}</b>",
        f"✅ Зашло: <b>{live_ok}</b>",
        f"❌ Не зашло: <b>{live_bad}</b>",
        f"⏳ Ещё в игре: <b>{live_wait}</b>",
        "ℹ️ Повторные обновления матча в число сигналов не входят.",
    ]
    if settled:
        lines.append(f"🎯 Проходимость завершённых сигналов: <b>{live_rate}%</b>")
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
