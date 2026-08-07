"""
Модуль уведомлений Telegram
Отправка красивых сообщений о сигналах
"""

import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any
import logging

from config import config
from brain.analyzer import SignalType, get_signal_description

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Класс для отправки уведомлений в Telegram"""
    
    def __init__(self):
        self.bot_token = config.TELEGRAM_BOT_TOKEN
        self.chat_id = config.TELEGRAM_CHAT_ID
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение или создание HTTP сессии"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        """Закрытие сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    def is_configured(self) -> bool:
        """Проверка настроен ли бот"""
        return bool(self.bot_token and self.chat_id)
    
    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Отправка сообщения в Telegram
        
        Args:
            text: Текст сообщения
            parse_mode: Режим парсинга (HTML, Markdown, etc.)
            
        Returns:
            True если сообщение отправлено успешно
        """
        if not self.is_configured():
            logger.warning("Telegram бот не настроен (отсутствует токен или chat_id)")
            return False
        
        session = await self._get_session()
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': True
        }
        
        try:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info("Сообщение успешно отправлено в Telegram")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка отправки в Telegram: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Исключение при отправке в Telegram: {e}")
            return False
    
    async def send_signal(
        self,
        home_team: str,
        away_team: str,
        league: str,
        start_time: datetime,
        initial_coef: float,
        current_coef: float,
        drop_percent: float,
        signal_type: SignalType,
        highlightly_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Отправка уведомления о сигнале
        
        Args:
            home_team: Домашняя команда
            away_team: Гостевая команда
            league: Название лиги/турнира
            start_time: Время начала матча
            initial_coef: Начальный коэффициент
            current_coef: Текущий коэффициент
            drop_percent: Процент падения
            signal_type: Тип сигнала
            highlightly_data: Данные подтверждения от Highlightly
            
        Returns:
            True если сообщение отправлено успешно
        """
        # Формирование заголовка в зависимости от типа сигнала
        if signal_type == SignalType.PANIC:
            header = "🚨 <b>ПАНИКА/АНОМАЛИЯ!</b>"
            emoji = "🔥"
        elif signal_type == SignalType.SIGNAL:
            header = "⚡ <b>СИГНАЛ!</b>"
            emoji = "⚽"
        else:
            header = "📊 <b>Движение коэффициентов</b>"
            emoji = "📈"
        
        # Форматирование времени
        time_str = start_time.strftime("%d.%m.%Y %H:%M") if start_time else "Не указано"
        
        # Основная информация о матче
        match_info = (
            f"{emoji} <b>{home_team} vs {away_team}</b>\n"
            f"🏆 <i>{league}</i>\n"
            f"🕒 {time_str}"
        )
        
        # Информация о коэффициенте
        coef_info = (
            f"\n\n<b>Коэффициент на ТБ (2.5):</b>\n"
            f"📉 Был: <code>{initial_coef:.2f}</code>\n"
            f"📉 Стал: <code>{current_coef:.2f}</code>\n"
            f"🔻 Падение: <b>{drop_percent:.1f}%</b>"
        )
        
        # Обоснование
        description = get_signal_description(signal_type)
        justification = f"\n\n<b>Обоснование:</b>\n{description}"
        
        # Данные от Highlightly если есть
        highlightly_note = ""
        if highlightly_data:
            confidence = highlightly_data.get('confidence', 0)
            recommendation = highlightly_data.get('recommendation', '')
            avg_goals = highlightly_data.get('avg_goals', {})
            
            if confidence > 0:
                highlightly_note += f"\n\n✅ <b>Подтверждение Highlightly:</b>\n"
                highlightly_note += f"Уверенность: {confidence * 100:.0f}%\n"
                if recommendation:
                    highlightly_note += f"Рекомендация: {recommendation}\n"
                if avg_goals and 'combined_avg' in avg_goals:
                    highlightly_note += f"Средний тотал команд: {avg_goals['combined_avg']:.2f}"
        elif signal_type.value in ['signal', 'panic']:
            highlightly_note = "\n\nℹ️ <i>Ожидание подтверждения от Highlightly...</i>"
        
        # Сборка полного сообщения
        message = (
            f"{header}\n\n"
            f"{match_info}"
            f"{coef_info}"
            f"{justification}"
            f"{highlightly_note}"
            f"\n\n<i>GoolBot | Мониторинг коэффициентов</i>"
        )
        
        return await self.send_message(message)
    
    async def send_summary(
        self,
        total_matches: int,
        signals_count: int,
        smart_money_count: int,
        panic_count: int
    ) -> bool:
        """
        Отправка ежедневной сводки
        
        Args:
            total_matches: Всего матчей на мониторинге
            signals_count: Количество сигналов
            smart_money_count: Количество "умных денег"
            panic_count: Количество паник-сигналов
        """
        now = datetime.now().strftime("%d.%m.%Y %H:%M")
        
        message = (
            f"📊 <b>Ежедневная сводка GoolBot</b>\n"
            f"<i>{now}</i>\n\n"
            f"📈 Матчей на мониторинге: <b>{total_matches}</b>\n"
            f"⚡ Сигналов: <b>{signals_count}</b>\n"
            f"💰 Умные деньги: <b>{smart_money_count}</b>\n"
            f"🚨 Паника: <b>{panic_count}</b>\n\n"
            f"<i>Продолжаю мониторинг...</i>"
        )
        
        return await self.send_message(message)
    
    async def send_error(self, error_message: str) -> bool:
        """Отправка сообщения об ошибке"""
        message = (
            f"❌ <b>Ошибка GoolBot</b>\n\n"
            f"<code>{error_message}</code>\n\n"
            f"<i>Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>"
        )
        return await self.send_message(message)
    
    async def send_startup_notification(self) -> bool:
        """Отправка уведомления о запуске бота"""
        message = (
            f"✅ <b>GoolBot запущен!</b>\n\n"
            f"🤖 Бот готов к мониторингу коэффициентов.\n"
            f"📊 Сканирование матчей каждые {config.SCAN_INTERVAL_MINUTES} мин.\n"
            f"🧹 Очистка БД в {config.CLEANUP_HOUR}:00\n\n"
            f"<i>Ожидаю ночного скана в {config.NIGHT_SCAN_HOUR}:00...</i>"
        )
        return await self.send_message(message)


# Singleton instance
_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """Получение singleton экземпляра нотификатора"""
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
