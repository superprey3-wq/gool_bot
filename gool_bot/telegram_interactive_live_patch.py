"""Interactive Telegram browser for active GOOL signals.

Adds paginated inline buttons to `В игре`. A tap opens the stored signal snapshot
inside Telegram; no external web page is required. Analytics/signal selection is
not changed by this patch.
"""
from __future__ import annotations

import html
from datetime import datetime

import telegram_subscribers as tg

_PAGE_SIZE = 8
_original_callback = tg._handle_callback


def _safe(value, default="—"):
    if value is None or value == "":
        return default
    return html.escape(str(value))


def _league(row: dict) -> str:
    for key in ("league", "tournament", "competition", "league_name", "competition_name"):
        if row.get(key):
            return str(row[key])
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    for key in ("league", "tournament", "competition"):
        if meta.get(key):
            return str(meta[key])
    return "Турнир не записан"


def _probability(row: dict):
    # Probability of the actual event, not GOOL diagnostic score.
    keys = (
        "event_probability", "probability", "goal_probability", "prob_goal",
        "p_goal", "p_event", "second_half_probability", "first_half_probability",
    )
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            x = float(value)
            if 0 <= x <= 1:
                x *= 100
            if 0 <= x <= 100:
                return round(x)
        except (TypeError, ValueError):
            pass
    primary = row.get("primary") if isinstance(row.get("primary"), dict) else {}
    for key in keys:
        value = primary.get(key)
        if value is None:
            continue
        try:
            x = float(value)
            if 0 <= x <= 1:
                x *= 100
            if 0 <= x <= 100:
                return round(x)
        except (TypeError, ValueError):
            pass
    return None


def _gool_score(row: dict):
    for key in ("gool_score", "model_score", "score", "rating", "signal_score"):
        value = row.get(key)
        try:
            x = float(value)
            if 0 <= x <= 100:
                return round(x)
        except (TypeError, ValueError):
            pass
    return None


def _stat(row: dict, *keys):
    pools = [row]
    for name in ("stats", "live_stats", "snapshot", "entry_stats"):
        if isinstance(row.get(name), dict):
            pools.append(row[name])
    for pool in pools:
        for key in keys:
            if pool.get(key) is not None:
                return pool.get(key)
    return None


def _row_key(row: dict) -> str:
    return f"{row.get('event_id')}|{row.get('engine') or 'core'}"


def _find_row(event_id: str, engine: str):
    rows = tg._active_signal_rows()
    exact = [r for r in rows if str(r.get("event_id")) == event_id and str(r.get("engine") or "core") == engine]
    if exact:
        return exact[0]
    return next((r for r in rows if str(r.get("event_id")) == event_id), None)


def _list_text(rows, page: int):
    pages = max(1, (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * _PAGE_SIZE
    lines = [
        f"🟢 <b>В ИГРЕ — {len(rows)}</b>",
        "<i>Нажми на матч — открою сохранённые данные сигнала внутри Telegram.</i>",
        "",
    ]
    for row in rows[start:start + _PAGE_SIZE]:
        minute = row.get("minute")
        p = _probability(row)
        lines.append(
            f"⏳ <b>{_safe(row.get('home'))} — {_safe(row.get('away'))}</b>\n"
            f"↳ {_safe(tg._engine_label(row))} · {_safe(_league(row))} · "
            f"вход {_safe(str(minute) + chr(39) if minute is not None else '—')} · "
            f"{_safe(row.get('score_at_signal'))}" + (f" · P <b>{p}%</b>" if p is not None else "")
        )
    return "\n".join(lines), page, pages


def _list_keyboard(rows, page: int):
    pages = max(1, (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    start = page * _PAGE_SIZE
    buttons = []
    for row in rows[start:start + _PAGE_SIZE]:
        home = str(row.get("home") or "?")
        away = str(row.get("away") or "?")
        label = f"⚽ {home} — {away}"
        if len(label) > 55:
            label = label[:52] + "…"
        event_id = str(row.get("event_id") or "")
        engine = str(row.get("engine") or "core")
        data = f"sig:{event_id}:{engine}"
        if len(data.encode("utf-8")) <= 64:
            buttons.append([{"text": label, "callback_data": data}])
    nav = []
    if page > 0:
        nav.append({"text": "⬅️", "callback_data": f"ig:{page-1}"})
    nav.append({"text": f"{page+1}/{pages}", "callback_data": f"ig:{page}"})
    if page + 1 < pages:
        nav.append({"text": "➡️", "callback_data": f"ig:{page+1}"})
    buttons.append(nav)
    buttons.append([{"text": "🔄 Обновить список", "callback_data": f"ig:{page}"}])
    return {"inline_keyboard": buttons}


def _send_live(chat_id) -> None:
    rows = tg._active_signal_rows()
    if not rows:
        tg._send_reply(chat_id, "🟢 <b>В ИГРЕ</b>\n\nСейчас незакрытых сигналов нет.")
        return
    text, page, _ = _list_text(rows, 0)
    tg._post_message(chat_id, text, _list_keyboard(rows, page))


def _details(row: dict) -> str:
    try:
        when = datetime.fromtimestamp(int(row.get("created_ts", 0)), tg.MOSCOW).strftime("%d.%m %H:%M")
    except Exception:
        when = "—"
    p = _probability(row)
    gs = _gool_score(row)
    shots = _stat(row, "shots", "total_shots", "shots_total")
    sot = _stat(row, "shots_on_target", "sot", "on_target")
    xg = _stat(row, "xg", "xG")
    xgot = _stat(row, "xgot", "xGoT")
    pressure = _stat(row, "live_pressure", "pressure")
    threat = _stat(row, "threat")
    history = _stat(row, "history", "history_score")
    sources = _stat(row, "sources", "source_count")
    reason = row.get("explanation") or row.get("why") or row.get("signal_reason_text")

    lines = [
        "🎯 <b>GOOL · СИГНАЛ</b>", "",
        f"⚽ <b>{_safe(row.get('home'))} — {_safe(row.get('away'))}</b>",
        f"🏆 {_safe(_league(row))}",
        f"🧠 {_safe(tg._engine_label(row))}",
        f"⏱ Вход: <b>{_safe(row.get('minute'))}' · {_safe(row.get('score_at_signal'))}</b> · {when}",
    ]
    if p is not None:
        lines.append(f"🎯 Вероятность события: <b>{p}%</b>")
    if gs is not None:
        lines.append(f"📈 GOOL score: <b>{gs}/100</b>")
    metrics = []
    if xg is not None: metrics.append(f"xG {_safe(xg)}")
    if xgot is not None: metrics.append(f"xGoT {_safe(xgot)}")
    if shots is not None: metrics.append(f"удары {_safe(shots)}")
    if sot is not None: metrics.append(f"в створ {_safe(sot)}")
    if metrics:
        lines += ["", "📊 <b>На момент сигнала</b>", " · ".join(metrics)]
    aux = []
    if pressure is not None: aux.append(f"pressure {_safe(pressure)}")
    if threat is not None: aux.append(f"threat {_safe(threat)}")
    if history is not None: aux.append(f"history {_safe(history)}")
    if sources is not None: aux.append(f"источники {_safe(sources)}")
    if aux:
        lines.append(" · ".join(aux))
    if reason:
        lines += ["", "💡 <b>Почему был вход</b>", _safe(reason)]
    lines += ["", "<i>Это сохранённый снимок ENTRY — именно те данные, на которых был дан сигнал.</i>"]
    return "\n".join(lines)


def _detail_keyboard(row: dict):
    event_id = str(row.get("event_id") or "")
    return {"inline_keyboard": [
        [{"text": "🖼 Карточка сигнала", "callback_data": f"show:{event_id}"}],
        [{"text": "⬅️ К матчам", "callback_data": "ig:0"}, {"text": "🔄 Обновить", "callback_data": f"sig:{event_id}:{row.get('engine') or 'core'}"}],
    ]}


def _interactive_callback(query: dict) -> None:
    callback_id = query.get("id")
    data = str(query.get("data") or "")
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not callback_id or chat_id is None:
        return _original_callback(query)

    if data.startswith("ig:"):
        try:
            page = int(data.split(":", 1)[1])
        except ValueError:
            page = 0
        rows = tg._active_signal_rows()
        text, page, _ = _list_text(rows, page)
        tg._answer_callback(callback_id, "Обновлено")
        tg._post_message(chat_id, text, _list_keyboard(rows, page))
        return

    if data.startswith("sig:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            tg._answer_callback(callback_id, "Некорректный сигнал")
            return
        row = _find_row(parts[1], parts[2])
        if not row:
            tg._answer_callback(callback_id, "Сигнал уже закрыт")
            tg._post_message(chat_id, "ℹ️ Этот сигнал уже закрыт и вышел из списка «В игре».", {"inline_keyboard": [[{"text": "⬅️ К матчам", "callback_data": "ig:0"}]]})
            return
        tg._answer_callback(callback_id, "Открываю сигнал")
        tg._post_message(chat_id, _details(row), _detail_keyboard(row))
        return

    return _original_callback(query)


tg._send_live = _send_live
tg._handle_callback = _interactive_callback
tg.BUILD_ID = "GOOL-PROD-TG-INTERACTIVE-1"
