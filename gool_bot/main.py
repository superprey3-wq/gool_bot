"""
Основной модуль бота GoolBot
Координация всех компонентов системы
"""

import asyncio
import logging
from datetime import datetime, time
from typing import List, Dict, Any, Optional

from config import config
from db import (
    init_db,
    save_match,
    get_all_matches,
    update_match_coef,
    cleanup_old_matches,
    log_message,
    get_signal_statistics
)
from api_client.infersports import get_infersports_client
from api_client.highlightly import get_highlightly_client
from brain.analyzer import (
    process_match_signal,
    should_request_highlightly_confirmation,
    SignalType
)
from notifier.telegram import get_notifier

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('gool_bot.log', encoding='utf-8')
    ]
)

logger = logging.getLogger(__name__)


class GoolBot:
    """Основной класс бота"""
    
    def __init__(self):
        self.infersports = get_infersports_client()
        self.highlightly = get_highlightly_client()
        self.notifier = get_notifier()
        self.is_running = False
        self._cleanup_done_today = False
    
    async def start(self):
        """Запуск бота"""
        logger.info("Запуск GoolBot...")
        
        # Инициализация БД
        init_db()
        logger.info("База данных инициализирована")
        
        self.is_running = True
        
        # Отправка уведомления о запуске
        if self.notifier.is_configured():
            await self.notifier.send_startup_notification()
        
        # Проверка времени для ночного скана
        now = datetime.now()
        
        # Если сейчас время ночного скана (около 00:00), выполняем его сразу
        if now.hour == config.NIGHT_SCAN_HOUR and now.minute < 5:
            logger.info("Выполнение ночного скана при запуске")
            await self.night_scan()
        
        # Запуск основного цикла
        await self.run_monitoring_loop()
    
    async def run_monitoring_loop(self):
        """Основной цикл мониторинга"""
        logger.info(f"Запуск цикла мониторинга (интервал: {config.SCAN_INTERVAL_MINUTES} мин)")
        
        while self.is_running:
            try:
                now = datetime.now()
                
                # Проверка на ночной скан (00:00)
                if now.hour == config.NIGHT_SCAN_HOUR and now.minute == 0:
                    await self.night_scan()
                    await asyncio.sleep(60)  # Ждем минуту чтобы не дублировать
                    continue
                
                # Проверка на очистку БД (23:00)
                if now.hour == config.CLEANUP_HOUR and now.minute == 0 and not self._cleanup_done_today:
                    await self.cleanup_database()
                    self._cleanup_done_today = True
                    await asyncio.sleep(60)
                    continue
                
                # Сброс флага очистки если перешли на новый день
                if now.hour == 0 and now.minute == 0:
                    self._cleanup_done_today = False
                
                # Обычный мониторинг коэффициентов
                await self.monitor_coefficients()
                
                # Ожидание следующего цикла
                await asyncio.sleep(config.SCAN_INTERVAL_MINUTES * 60)
                
            except asyncio.CancelledError:
                logger.info("Мониторинг остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}", exc_info=True)
                if self.notifier.is_configured():
                    await self.notifier.send_error(str(e))
                await asyncio.sleep(60)  # Пауза перед повторной попыткой
    
    async def night_scan(self):
        """
        Ночной скан - получение всех матчей на ближайшие 48 часов
        Выполняется в 00:00
        """
        logger.info("=" * 50)
        logger.info("НАЧАНИЕ НОЧНОГО СКАНА")
        logger.info("=" * 50)
        
        try:
            # Получение матчей от Infersports
            matches = await self.infersports.get_matches(hours_ahead=config.MATCHES_HOURS_AHEAD)
            
            if not matches:
                logger.warning("Не удалось получить матчи от Infersports")
                return
            
            logger.info(f"Получено {len(matches)} матчей")
            
            # Сохранение матчей в БД
            saved_count = 0
            for match in matches:
                if match['initial_coef_over'] > 0:  # Только матчи с коэффициентами
                    save_match(match)
                    saved_count += 1
            
            logger.info(f"Сохранено {saved_count} матчей в базу данных")
            
            # Уведомление о результатах скана
            if self.notifier.is_configured() and saved_count > 0:
                message = (
                    f"🌙 <b>Ночной скан завершен</b>\n\n"
                    f"Найдено матчей: {len(matches)}\n"
                    f"Сохранено с коэффициентами: {saved_count}\n\n"
                    f"Приступаю к мониторингу..."
                )
                await self.notifier.send_message(message)
            
            log_message("INFO", f"Ночной скан: сохранено {saved_count} матчей")
            
        except Exception as e:
            logger.error(f"Ошибка при ночном скане: {e}", exc_info=True)
            if self.notifier.is_configured():
                await self.notifier.send_error(f"Ошибка ночного скана: {str(e)}")
    
    async def monitor_coefficients(self):
        """
        Мониторинг текущих коэффициентов
        Выполняется каждые 5 минут
        """
        logger.debug("Начало мониторинга коэффициентов")
        
        try:
            # Получение всех матчей из БД
            matches = get_all_matches()
            
            if not matches:
                logger.debug("Нет матчей для мониторинга")
                return
            
            logger.info(f"Мониторинг {len(matches)} матчей")
            
            # Получение ID матчей для запроса коэффициентов
            match_ids = [match['id'] for match in matches]
            
            # Получение текущих коэффициентов от Infersports
            current_odds = await self.infersports.get_all_current_odds(match_ids)
            
            signals_sent = 0
            smart_money_count = 0
            
            # Анализ каждого матча
            for match in matches:
                match_id = match['id']
                
                if match_id not in current_odds:
                    continue
                
                current_coef = current_odds[match_id].get('over_coef', 0)
                
                if current_coef <= 0:
                    continue
                
                initial_coef = match['initial_coef_over']
                
                # Обновление коэффициента в БД
                update_match_coef(match_id, current_coef)
                
                # Анализ сигнала
                signal_result = await process_match_signal(
                    match_id=match_id,
                    home_team=match['home_team'],
                    away_team=match['away_team'],
                    initial_coef=initial_coef,
                    current_coef=current_coef
                )
                
                if signal_result is None:
                    continue
                
                # Обработка сильных сигналов (15%+)
                if signal_result.should_send:
                    # Попытка получить подтверждение от Highlightly
                    highlightly_data = None
                    
                    if should_request_highlightly_confirmation(signal_result.drop_percent):
                        try:
                            # Запрос к Highlightly только если не исчерпан лимит
                            if not self.highlightly.is_rate_limited():
                                highlightly_data = await self.highlightly.get_match_analysis(
                                    match['home_team'],
                                    match['away_team']
                                )
                                logger.info(f"Получены данные от Highlightly для {match['home_team']} vs {match['away_team']}")
                            else:
                                logger.warning("Лимит запросов к Highlightly исчерпан, отправляем сигнал без подтверждения")
                        except Exception as e:
                            logger.warning(f"Не удалось получить данные от Highlightly: {e}")
                            # Важно: сигнал ВСЕ РАВНО отправляется даже если Highlightly не ответил
                    
                    # Отправка уведомления в Telegram
                    if self.notifier.is_configured():
                        start_time = datetime.fromisoformat(match['start_time']) if match['start_time'] else None
                        
                        sent = await self.notifier.send_signal(
                            home_team=match['home_team'],
                            away_team=match['away_team'],
                            league=match.get('league', ''),
                            start_time=start_time,
                            initial_coef=initial_coef,
                            current_coef=current_coef,
                            drop_percent=signal_result.drop_percent,
                            signal_type=signal_result.signal_type,
                            highlightly_data=highlightly_data
                        )
                        
                        if sent:
                            signals_sent += 1
                            logger.info(f"Сигнал отправлен: {match['home_team']} vs {match['away_team']}")
                
                # Подсчет умных денег
                if signal_result.signal_type == SignalType.SMART_MONEY:
                    smart_money_count += 1
            
            if signals_sent > 0 or smart_money_count > 0:
                logger.info(f"Цикл завершен: сигналов={signals_sent}, умные деньги={smart_money_count}")
            
        except Exception as e:
            logger.error(f"Ошибка при мониторинге коэффициентов: {e}", exc_info=True)
    
    async def cleanup_database(self):
        """
        Очистка базы данных от старых матчей
        Выполняется в 23:00
        """
        logger.info("Начало очистки базы данных")
        
        try:
            deleted_count = cleanup_old_matches(days_old=1)
            logger.info(f"Удалено {deleted_count} старых матчей")
            
            if self.notifier.is_configured() and deleted_count > 0:
                message = f"🧹 <b>Очистка БД завершена</b>\n\nУдалено старых матчей: {deleted_count}"
                await self.notifier.send_message(message)
            
            log_message("INFO", f"Очистка БД: удалено {deleted_count} матчей")
            
        except Exception as e:
            logger.error(f"Ошибка при очистке БД: {e}", exc_info=True)
    
    async def stop(self):
        """Остановка бота"""
        logger.info("Остановка GoolBot...")
        self.is_running = False
        
        # Закрытие сессий
        await self.infersports.close()
        await self.highlightly.close()
        await self.notifier.close()
        
        logger.info("GoolBot остановлен")


async def main():
    """Точка входа"""
    bot = GoolBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
