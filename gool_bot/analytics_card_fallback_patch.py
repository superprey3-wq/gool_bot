"""Keep CORE text fallback analytics-first when PNG rendering is unavailable."""
from __future__ import annotations
import telegram_image_signal_patch as tip

def _compact_fallback(m,recs,kind,master,xg):
    if kind=="goal":
        return (f"✅ <b>GOOL AI • СИГНАЛ ПОДТВЕРЖДЁН — ГОЛ</b>\n\n"
                f"⚽ <b>{m.home} — {m.away}</b>\n"
                f"⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>")
    probs=tip._display_probabilities(m,master,xg)
    return (f"🔥 <b>GOOL AI • СИГНАЛ: ОЖИДАЕМ ГОЛ</b>\n\n"
            f"⚽ <b>{m.home} — {m.away}</b>\n"
            f"⏱ {m.minute}' | <b>{m.home_score}:{m.away_score}</b>\n"
            f"🧠 GOOL: <b>{float(master or 0):.0f}/100</b>\n"
            f"📈 P(ещё гол): <b>{int(probs.get('one_goal',0) or 0)}%</b>")

tip._compact_fallback=_compact_fallback
