"""
Brain модуль - анализ и обработка сигналов
"""

from brain.analyzer import (
    SignalType,
    SignalResult,
    calculate_drop_percent,
    analyze_signal,
    process_match_signal,
    should_request_highlightly_confirmation,
    get_signal_description
)

__all__ = [
    'SignalType',
    'SignalResult',
    'calculate_drop_percent',
    'analyze_signal',
    'process_match_signal',
    'should_request_highlightly_confirmation',
    'get_signal_description'
]
