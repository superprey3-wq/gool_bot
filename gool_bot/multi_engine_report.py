"""Report helpers for GOOL MULTI-ENGINE.
Keeps CORE, first-half hunter and second-half late-risk statistics separate.
"""
from __future__ import annotations
from multi_engine import CORE,HT_HUNTER,LATE_RISK

def engine_of(row:dict)->str:
    value=str(row.get("engine") or row.get("signal_engine") or "").strip().lower()
    if value in {HT_HUNTER,"ht_hunter","ht","first_half"}:return HT_HUNTER
    if value in {LATE_RISK,"late_risk","risk","second_half"}:return LATE_RISK
    return CORE

def split_rows(rows):
    out={CORE:[],HT_HUNTER:[],LATE_RISK:[]}
    for row in rows:out[engine_of(row)].append(row)
    return out

def _result(row):
    v=str(row.get("result") or "pending").strip().lower()
    if v in {"+","win","won"}:return "win"
    if v in {"-","loss","lost"}:return "loss"
    return "pending"

def _section(title,rows):
    wins=sum(_result(r)=="win" for r in rows);losses=sum(_result(r)=="loss" for r in rows);pending=len(rows)-wins-losses
    settled=wins+losses;rate=round(wins/settled*100) if settled else 0
    lines=[title,f"Сигналов: <b>{len(rows)}</b> · ✅ <b>{wins}</b> · ❌ <b>{losses}</b> · ⏳ <b>{pending}</b>"]
    if settled:lines.append(f"🎯 Проходимость: <b>{rate}%</b>")
    odds=[]
    for r in rows:
        try:
            o=float(r.get("odd") or r.get("live_odd") or 0)
            if o>1:odds.append(o)
        except Exception:pass
    if odds:lines.append(f"💰 Средний LIVE-кэф: <b>{sum(odds)/len(odds):.2f}</b>")
    return "\n".join(lines)

def build_engine_sections(rows)->str:
    groups=split_rows(rows)
    return "\n\n".join([
        _section("🟡 <b>ГЛАВНЫЕ СИГНАЛЫ</b>",groups[CORE]),
        _section("🔵 <b>ПЕРВЫЙ ТАЙМ · HT HUNTER</b>",groups[HT_HUNTER]),
        _section("🔴 <b>ВТОРОЙ ТАЙМ · LATE RISK</b>",groups[LATE_RISK]),
    ])
