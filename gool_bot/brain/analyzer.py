"""
Модуль анализа сигналов (Brain)
Определяет тип сигнала на основе процента падения коэффициента
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
import logging

from config import config
from db import save_signal, log_message

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Типы сигналов"""
    NOISE = "noise"              # 3-7%: Шум (игнорировать)
    SMART_MONEY = "smart_money"  # 8-14%: Умные деньги (логировать)
    SIGNAL = "signal"            # 15%+: СИГНАЛ
    PANIC = "panic"              # 25%+: Паника/Аномалия


@dataclass
class SignalResult:
    """Результат анализа сигнала"""
    signal_type: SignalType
    drop_percent: float
    initial_coef: float
    current_coef: float
    should_send: bool
    should_log: bool
    priority: int  # 1 = низкий, 3 = высокий
    
    def __str__(self) -> str:
        return f"Signal({self.signal_type.value}, {self.drop_percent:.1f}%, send={self.should_send})"


def calculate_drop_percent(initial_coef: float, current_coef: float) -> float:
    """
    Расчет процента падения коэффициента
    
    Формула: ((initial - current) / initial) * 100
    
    Args:
        initial_coef: Начальный коэффициент
        current_coef: Текущий коэффициент
        
    Returns:
        Процент падения (положительное число если коэффициент упал)
    """
    if initial_coef <= 0:
        return 0.0
    
    drop = ((initial_coef - current_coef) / initial_coef) * 100
    return max(0.0, drop)  # Не возвращаем отрицательные значения (рост коэффициента)


def analyze_signal(initial_coef: float, current_coef: float) -> SignalResult:
    """
    Анализ изменения коэффициента и определение типа сигнала
    
    Args:
        initial_coef: Начальный коэффициент
        current_coef: Текущий коэффициент
        
    Returns:
        Результат анализа сигнала
    """
    drop_percent = calculate_drop_percent(initial_coef, current_coef)
    
    # Определение типа сигнала на основе порогов
    if drop_percent < config.THRESHOLD_NOISE_MIN:
        # Меньше 3% - незначительное изменение
        return SignalResult(
            signal_type=SignalType.NOISE,
            drop_percent=drop_percent,
            initial_coef=initial_coef,
            current_coef=current_coef,
            should_send=False,
            should_log=False,
            priority=0
        )
    
    elif drop_percent < config.THRESHOLD_SMART_MONEY_MIN:
        # 3-7% - шум
        return SignalResult(
            signal_type=SignalType.NOISE,
            drop_percent=drop_percent,
            initial_coef=initial_coef,
            current_coef=current_coef,
            should_send=False,
            should_log=True,
            priority=1
        )
    
    elif drop_percent < config.THRESHOLD_SIGNAL:
        # 8-14% - умные деньги
        return SignalResult(
            signal_type=SignalType.SMART_MONEY,
            drop_percent=drop_percent,
            initial_coef=initial_coef,
            current_coef=current_coef,
            should_send=False,
            should_log=True,
            priority=2
        )
    
    elif drop_percent < config.THRESHOLD_PANIC:
        # 15-24% - сигнал
        return SignalResult(
            signal_type=SignalType.SIGNAL,
            drop_percent=drop_percent,
            initial_coef=initial_coef,
            current_coef=current_coef,
            should_send=True,
            should_log=True,
            priority=3
        )
    
    else:
        # 25%+ - паника/аномалия
        return SignalResult(
            signal_type=SignalType.PANIC,
            drop_percent=drop_percent,
            initial_coef=initial_coef,
            current_coef=current_coef,
            should_send=True,
            should_log=True,
            priority=4
        )


async def process_match_signal(
    match_id: str,
    home_team: str,
    away_team: str,
    initial_coef: float,
    current_coef: float,
    highlightly_data: Optional[Dict[str, Any]] = None
) -> Optional[SignalResult]:
    """
    Обработка сигнала для матча
    
    Args:
        match_id: ID матча
        home_team: Домашняя команда
        away_team: Гостевая команда
        initial_coef: Начальный коэффициент
        current_coef: Текущий коэффициент
        highlightly_data: Данные от Highlightly (опционально)
        
    Returns:
        Результат анализа или None если изменений нет
    """
    result = analyze_signal(initial_coef, current_coef)
    
    if result.signal_type == SignalType.NOISE and not result.should_log:
        # Полностью игнорируем незначительные изменения
        return None
    
    # Логирование
    if result.should_log:
        log_msg = f"[{result.signal_type.value.upper()}] {home_team} vs {away_team}: " \
                  f"Кэф упал с {initial_coef:.2f} до {current_coef:.2f} ({result.drop_percent:.1f}%)"
        logger.info(log_msg)
        log_message("INFO", log_msg)
    
    # Сохранение сигнала в БД если это значимое событие
    if result.should_log or result.should_send:
        confirmed = highlightly_data is not None
        highlightly_json = str(highlightly_data) if highlightly_data else None
        
        save_signal(
            match_id=match_id,
            signal_type=result.signal_type.value,
            drop_percent=result.drop_percent,
            initial_coef=initial_coef,
            current_coef=current_coef,
            confirmed=confirmed,
            highlightly_data=highlightly_json
        )
    
    return result


def should_request_highlightly_confirmation(drop_percent: float) -> bool:
    """
    Определение необходимости запроса подтверждения от Highlightly
    
    Запрашиваем подтверждение только для сильных сигналов (15%+)
    
    Args:
        drop_percent: Процент падения коэффициента
        
    Returns:
        True если нужно запрашивать подтверждение
    """
    return drop_percent >= config.THRESHOLD_SIGNAL


def get_signal_description(signal_type: SignalType) -> str:
    """Получение описания типа сигнала на русском языке"""
    descriptions = {
        SignalType.NOISE: "Незначительное изменение (шум)",
        SignalType.SMART_MONEY: "Умные деньги - заметное движение коэффициента",
        SignalType.SIGNAL: "СИГНАЛ - Сильное падение коэффициента!",
        SignalType.PANIC: "🚨 ПАНИКА/АНОМАЛИЯ - Критическое падение!"
    }
    return descriptions.get(signal_type, "Неизвестный сигнал")
