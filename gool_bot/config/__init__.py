"""
Конфигурация бота GoolBot
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Конфигурация приложения"""
    
    # API ключи
    INFERSPORTS_API_KEY: str = "isk_r7mHQpL6XtQCNkQascBBCyqEVxSzi2nf"
    HIGHLIGHTLY_API_KEY: str = "7372496a-664b-47bc-8844-b4fc602f109d"
    
    # Telegram настройки
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Настройки порогов
    THRESHOLD_NOISE_MIN: float = 3.0      # 3-7%: Шум (игнорировать)
    THRESHOLD_NOISE_MAX: float = 7.0
    THRESHOLD_SMART_MONEY_MIN: float = 8.0  # 8-14%: Умные деньги (логировать)
    THRESHOLD_SMART_MONEY_MAX: float = 14.0
    THRESHOLD_SIGNAL: float = 15.0         # 15%+: СИГНАЛ
    THRESHOLD_PANIC: float = 25.0          # 25%+: Паника/Аномалия
    
    # Интервалы сканирования
    SCAN_INTERVAL_MINUTES: int = 5
    NIGHT_SCAN_HOUR: int = 0        # 00:00 - ночной скан
    CLEANUP_HOUR: int = 23          # 23:00 - очистка БД
    MATCHES_HOURS_AHEAD: int = 48   # Сканировать матчи на ближайшие 48 часов
    
    # База данных
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "gool_bot.db")
    
    # URL API
    INFERSPORTS_BASE_URL: str = "https://api.infersports.dev"
    HIGHLIGHTLY_BASE_URL: str = "https://api.highlightly.com"
    
    @classmethod
    def from_env(cls) -> "Config":
        """Загрузка конфигурации из переменных окружения"""
        return cls(
            INFERSPORTS_API_KEY=os.getenv("INFERSPORTS_API_KEY", cls.INFERSPORTS_API_KEY),
            HIGHLIGHTLY_API_KEY=os.getenv("HIGHLIGHTLY_API_KEY", cls.HIGHLIGHTLY_API_KEY),
            TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", cls.TELEGRAM_BOT_TOKEN),
            TELEGRAM_CHAT_ID=os.getenv("TELEGRAM_CHAT_ID", cls.TELEGRAM_CHAT_ID),
            DATABASE_PATH=os.getenv("DATABASE_PATH", cls.DATABASE_PATH),
        )


config = Config.from_env()
