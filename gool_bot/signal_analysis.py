"""All-time GOOL 2.0 analytics focused on football-signal quality."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from multi_engine import FIRST_HALF_GOAL, SECOND_HALF_OVER15
from signal_journal import all_signals

MOSCOW = ZoneInfo("Europe/Moscow")
_WIN = {"+", "win", "won"}
_LOSS = {"-", "loss", "lost"}


def _all_live_rows():
    return [r for r in all_signals() if r.get("kind") == "live"]


def _core_entries(rows):
    aux = {FIRST_HALF_GOAL, SECOND_HALF_OVER15}
    return [
        r for r in rows
        if str(r.get("reason") or "signal") in {"signal", "reentry"}
        and str(r.get("engine") or "core") not in aux
    ]


def _state(row):
    value = str(row.get("signal_result") or row.get("result") or "pending").strip().lower()
    if value in _WIN:
        return "win"
    if value in _LOSS:
        return "loss"
    return "pending"


def _num(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
    return None


def _bucket_minute(value):
    minute = int(value or 0)
    if minute <= 20:
        return "1–20'"
    if minute <= 40:
        return "21–40'"
    if minute <= 60:
        return "41–60'"
    if minute <= 74:
        return "61–74'"
    return "75+'"


def _bucket_rating(value):
    if value is None:
        return "нет данных"
    if value < 60:
        return "<60"
    if value < 70:
        return "60–69"
    if value < 80:
        return "70–79"
    if value < 90:
        return "80–89"
    return "90+"


def _time_to_goal(row):
    try:
        start = int(row.get("minute") or 0)
        goal = int(row.get("next_goal_minute") or row.get("result_minute") or 0)
        if goal >= start > 0:
            return goal - start
    except Exception:
        pass
    return None


def _settled(rows):
    return [(row, _state(row)) for row in rows if _state(row) != "pending"]


def _groups(items, keyfn):
    grouped = defaultdict(lambda: [0, 0, 0])
    for row, state in items:
        key = keyfn(row)
        grouped[key][0] += 1
        grouped[key][1] += int(state == "win")
        grouped[key][2] += int(state == "loss")
    return grouped


def _fmt_groups(title, grouped, order=None):
    lines = [f"<b>{title}</b>"]
    for key in order or list(grouped):
        if key not in grouped:
            continue
        total, wins, losses = grouped[key]
        hit = round(wins / total * 100) if total else 0
        lines.append(f"• {key}: <b>{wins}/{total} · {hit}%</b> · ❌ {losses}")
    return lines


def _summary_line(label, items):
    total = len(items)
    wins = sum(state == "win" for _, state in items)
    losses = sum(state == "loss" for _, state in items)
    hit = round(wins / total * 100) if total else 0
    times = [x for x in (_time_to_goal(row) for row, state in items if state == "win") if x is not None]
    suffix = f" · ⏱ {sum(times)/len(times):.1f} мин до гола" if times else ""
    return f"• {label}: <b>{total}</b> · ✅ {wins} · ❌ {losses} · 🎯 <b>{hit}%</b>{suffix}"


def _engine_section(title, rows):
    items = _settled(rows)
    lines = ["", title]
    if not items:
        return lines + ["• Пока нет закрытых сигналов."]
    lines.append(_summary_line("Итого", items))
    lines += [""] + _fmt_groups(
        "По минуте входа",
        _groups(items, lambda r: _bucket_minute(r.get("minute"))),
        ["1–20'", "21–40'", "41–60'", "61–74'", "75+'"],
    )
    ratings = _groups(items, lambda r: _bucket_rating(_num(r, "strategy_score", "master", "pressure")))
    if ratings:
        lines += [""] + _fmt_groups(
            "По рейтингу модели",
            ratings,
            ["<60", "60–69", "70–79", "80–89", "90+", "нет данных"],
        )
    return lines


def build_analysis_text():
    rows = _all_live_rows()
    core_rows = _core_entries(rows)
    core = _settled(core_rows)

    lines = [
        "🧠 <b>GOOL 2.0 — АНАЛИЗ ЗА ВСЁ ВРЕМЯ</b>",
        f"🗓 {datetime.now(MOSCOW).strftime('%d.%m.%Y %H:%M')}",
        "",
        "🟡 <b>CORE · КАЧЕСТВО СИГНАЛА НА ГОЛ</b>",
    ]

    if core:
        lines.append(_summary_line("Итого", core))
        primary = [x for x in core if str(x[0].get("reason") or "signal") == "signal"]
        reentry = [x for x in core if str(x[0].get("reason") or "signal") == "reentry"]
        lines += [
            "",
            "♻️ <b>Первичный vs re-entry</b>",
            _summary_line("Первичные", primary),
            _summary_line("Re-entry", reentry),
        ]
        lines += [""] + _fmt_groups(
            "⏱ По минуте входа",
            _groups(core, lambda r: _bucket_minute(r.get("minute"))),
            ["1–20'", "21–40'", "41–60'", "61–74'", "75+'"],
        )
        lines += [""] + _fmt_groups(
            "⭐ По рейтингу GOOL",
            _groups(core, lambda r: _bucket_rating(_num(r, "master", "pressure"))),
            ["<60", "60–69", "70–79", "80–89", "90+", "нет данных"],
        )
        lines += ["", "<b>Последние закрытые CORE:</b>"]
        for row, state in core[-10:]:
            mark = "✅" if state == "win" else "❌"
            extra = ""
            ttg = _time_to_goal(row)
            if ttg is not None and state == "win":
                extra = f" · гол через {ttg} мин"
            lines.append(f"{mark} {row.get('home')} — {row.get('away')} | {row.get('minute')}'{extra}")
    else:
        lines.append("Пока нет закрытых CORE-сигналов.")

    fh = [r for r in rows if str(r.get("engine") or "") == FIRST_HALF_GOAL]
    sh = [r for r in rows if str(r.get("engine") or "") == SECOND_HALF_OVER15]
    lines += _engine_section("🔵 <b>1-Й ТАЙМ · ГОЛ 15–25'</b>", fh)
    lines += _engine_section("🟣 <b>2-Й ТАЙМ · 2+ ГОЛА ПОСЛЕ ПЕРЕРЫВА</b>", sh)

    pending = sum(_state(r) == "pending" for r in rows)
    if pending:
        lines += ["", f"⏳ Сейчас незакрытых сигналов в журнале: <b>{pending}</b>."]
    lines += ["", "<i>Анализ оценивает только футбольный прогноз GOOL. Коэффициенты, ROI и CLV не влияют на качество сигнала.</i>"]
    return "\n".join(lines)
