"""
Конфигурация бота GoolBot.
Секреты читаются только из переменных окружения/GitHub Secrets.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    # API ключи — никогда не хранить реальные значения в репозитории.
    INFERSPORTS_API_KEY: str = ""
    HIGHLIGHTLY_API_KEY: str = ""

    # Telegram настройки
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Настройки порогов старого анализатора
    THRESHOLD_NOISE_MIN: float = 3.0
    THRESHOLD_NOISE_MAX: float = 7.0
    THRESHOLD_SMART_MONEY_MIN: float = 8.0
    THRESHOLD_SMART_MONEY_MAX: float = 14.0
    THRESHOLD_SIGNAL: float = 15.0
    THRESHOLD_PANIC: float = 25.0

    SCAN_INTERVAL_MINUTES: int = 5
    NIGHT_SCAN_HOUR: int = 0
    CLEANUP_HOUR: int = 23
    MATCHES_HOURS_AHEAD: int = 48

    DATABASE_PATH: str = "gool_bot.db"
    INFERSPORTS_BASE_URL: str = "https://api.infersports.dev"
    HIGHLIGHTLY_BASE_URL: str = "https://api.highlightly.com"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            INFERSPORTS_API_KEY=os.getenv("INFERSPORTS_API_KEY", ""),
            HIGHLIGHTLY_API_KEY=os.getenv("HIGHLIGHTLY_API_KEY", ""),
            TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID", ""),
            DATABASE_PATH=os.getenv("DATABASE_PATH", "gool_bot.db"),
        )


config = Config.from_env()
