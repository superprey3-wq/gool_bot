"""Optional Gemini analyst for GOOL.

Safe-by-default prototype: it is disabled unless GEMINI_AI_ENABLED=1 and
GEMINI_API_KEY is configured. It never replaces GOOL's own scoring logic.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

import requests

GEMINI_AI_ENABLED = os.getenv("GEMINI_AI_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
GEMINI_TIMEOUT_SECONDS = max(3, int(os.getenv("GEMINI_TIMEOUT_SECONDS", "12")))

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_RULES = """Ты футбольный AI-аналитик GOOL. Получаешь только факты от нашего алгоритма.
Не придумывай удары, xG, коэффициенты, минуту, счёт или историю. Если данных нет — так и считай.
Не обещай гол как гарантированный исход. Пиши живо, коротко и по-русски, но без ложной уверенности.
GOOL MASTER и внутренние расчёты являются основой; твоя задача — объяснить картину матча и дать дополнительную оценку.
Верни только JSON по заданной схеме.
"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ai_score": {"type": "INTEGER", "minimum": 0, "maximum": 100},
        "verdict": {
            "type": "STRING",
            "enum": ["WATCH", "PROMISING", "STRONG", "VERY_STRONG", "AVOID"],
        },
        "risk": {"type": "STRING", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "reason": {"type": "STRING"},
        "telegram_text": {"type": "STRING"},
    },
    "required": ["ai_score", "verdict", "risk", "reason", "telegram_text"],
}


def _disabled(reason: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "ai_score": None,
        "verdict": "DISABLED",
        "risk": None,
        "reason": reason,
        "telegram_text": "",
    }


def analyze_match(match_data: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Gemini for a second opinion on an already-selected GOOL candidate.

    Fail-open behaviour: any Gemini/API/parsing failure returns ok=False and the
    caller should keep the existing GOOL flow unchanged.
    """
    if not GEMINI_AI_ENABLED:
        return _disabled("GEMINI_AI_ENABLED is off")
    if not GEMINI_API_KEY:
        return _disabled("GEMINI_API_KEY is missing")

    prompt = (
        SYSTEM_RULES
        + "\nДанные матча от GOOL:\n"
        + json.dumps(match_data, ensure_ascii=False, separators=(",", ":"))
    )

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.55,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
        },
    }

    try:
        response = requests.post(
            API_URL.format(model=GEMINI_MODEL),
            headers={
                "x-goog-api-key": GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=GEMINI_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        raw = response.json()
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
        parsed["ai_score"] = max(0, min(100, int(parsed["ai_score"])))
        parsed["ok"] = True
        return parsed
    except Exception as exc:
        return _disabled(f"Gemini unavailable: {type(exc).__name__}: {exc}")
