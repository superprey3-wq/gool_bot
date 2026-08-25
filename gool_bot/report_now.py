"""On-demand GOOL 2.0 report focused on football-signal quality, not odds."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15
from signal_journal import all_signals

MOSCOW = ZoneInfo("Europe/Moscow")
_PENDING = {"", "pending", "wait", "waiting"}
_WIN = {"+", "win", "won"}
_LOSS = {"-", "loss", "lost"}


def _today_rows():
    today = datetime.now(MOSCOW).date()
    rows = []
    for row in all_signals():
        if row.get("kind") != "live":
            continue
        try:
            created = datetime.fromtimestamp(int(row.get("created_ts", 0)), MOSCOW)
        except Exception:
            continue
        if created.date() == today:
            rows.append(row)
    return rows


def _live_signal_rows(rows):
    aux = {FIRST_HALF_GOAL, SECOND_HALF_OVER15}
    return [
        r for r in rows
        if str(r.get("reason") or "signal") in {"signal", "reentry"}
        and str(r.get("engine") or "core") not in aux
    ]


def _engine_rows(rows, engine):
    return [r for r in rows if str(r.get("engine") or "") == engine]


def _state(row):
    value = str(row.get("signal_result") or row.get("result") or "pending").strip().lower()
    if value in _WIN:
        return "win"
    if value in _LOSS:
        return "loss"
    return "pending"


def _is_pending_entry(row):
    return _state(row) == "pending"


def _core_state(row):
    return _state(row), None


def _aux_state(row):
    return _state(row), None


def _market_label(row):
    return "аналитический сигнал"


def _time_to_goal(row):
    try:
        signal_minute = int(row.get("minute") or 0)
        goal_minute = int(row.get("next_goal_minute") or row.get("result_minute") or 0)
        if goal_minute >= signal_minute > 0:
            return goal_minute - signal_minute
    except Exception:
        pass
    return None


def _master(row):
    for key in ("master", "strategy_score", "pressure"):
        try:
            if row.get(key) is not None:
                return float(row.get(key))
        except Exception:
            pass
    return None


def _metrics(rows):
    states = [(r, _state(r)) for r in rows]
    wins = sum(s == "win" for _, s in states)
    losses = sum(s == "loss" for _, s in states)
    pending = sum(s == "pending" for _, s in states)
    settled = wins + losses
    hit = round(wins / settled * 100) if settled else 0
    goal_times = [x for x in (_time_to_goal(r) for r, s in states if s == "win") if x is not None]
    masters = [x for x in (_master(r) for r, _ in states) if x is not None]
    return {
        "states": states,
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "settled": settled,
        "hit": hit,
        "avg_goal_time": sum(goal_times) / len(goal_times) if goal_times else None,
        "avg_master": sum(masters) / len(masters) if masters else None,
    }


def _summary(title, rows):
    m = _metrics(rows)
    lines = ["", title, f"Сигналов: <b>{len(rows)}</b> · закрыто: <b>{m['settled']}</b> · ⏳ {m['pending']}"]
    lines.append(f"✅ подтверждено: <b>{m['wins']}</b> · ❌ не подтверждено: <b>{m['losses']}</b>")
    if m["settled"]:
        lines.append(f"🎯 Точность сигнала: <b>{m['hit']}%</b>")
    if m["avg_goal_time"] is not None:
        lines.append(f"⏱ Среднее время до подтверждающего гола: <b>{m['avg_goal_time']:.1f} мин</b>")
    if m["avg_master"] is not None:
        lines.append(f"🧠 Средний рейтинг модели: <b>{m['avg_master']:.1f}/100</b>")
    return lines, m


def build_live_signals_text():
    rows = [r for r in _today_rows() if _is_pending_entry(r)]
    if not rows:
        return "🟢 <b>В ИГРЕ</b>\n\nСейчас незакрытых сигналов нет."
    lines = [f"🟢 <b>В ИГРЕ — {len(rows)}</b>", "<i>Активные аналитические сигналы GOOL.</i>", ""]
    for row in rows[-20:]:
        engine = str(row.get("engine") or "core")
        label = "CORE · ГОЛ" if engine not in {FIRST_HALF_GOAL, SECOND_HALF_OVER15} else "1T · ГОЛ" if engine == FIRST_HALF_GOAL else "2T · 2+ ГОЛА"
        lines.append(f"⏳ <b>{row.get('home')} — {row.get('away')}</b>\n↳ {label} · {row.get('minute')}' · {row.get('score_at_signal')}")
    return "\n".join(lines)


def build_report_text():
    rows = _today_rows()
    core = _live_signal_rows(rows)
    fh = _engine_rows(rows, FIRST_HALF_GOAL)
    sh = _engine_rows(rows, SECOND_HALF_OVER15)
    initial = sum(str(r.get("reason") or "signal") == "signal" for r in core)
    reentries = sum(str(r.get("reason") or "signal") == "reentry" for r in core)

    lines = [
        "📊 <b>GOOL 2.0 — ОТЧЁТ НА СЕЙЧАС</b>",
        f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}",
        "",
        "🟡 <b>CORE · СИГНАЛ НА ГОЛ</b>",
        f"Первичных: <b>{initial}</b> · re-entry: <b>{reentries}</b>",
    ]
    core_lines, core_m = _summary("", core)
    lines += core_lines[1:]

    if core:
        lines.append("<b>Последние CORE:</b>")
        for row, state in core_m["states"][-8:]:
            mark = "✅" if state == "win" else "❌" if state == "loss" else "⏳"
            lines.append(f"{mark} {row.get('home')} — {row.get('away')} | {row.get('minute')}' · {row.get('score_at_signal')}")

    fh_lines, _ = _summary("🔵 <b>1-Й ТАЙМ · ГОЛ 15–25'</b>", fh)
    lines += fh_lines
    sh_lines, _ = _summary("🟣 <b>2-Й ТАЙМ · 2+ ГОЛА ПОСЛЕ ПЕРЕРЫВА</b>", sh)
    lines += sh_lines

    if not rows:
        lines += ["", "Сегодня в журнале пока нет сигналов."]
    lines += ["", "<i>Отчёт оценивает футбольные сигналы GOOL. Коэффициенты и результат ставки в эту статистику не входят.</i>"]
    return "\n".join(lines)
