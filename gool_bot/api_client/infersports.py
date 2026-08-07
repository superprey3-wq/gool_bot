"""
Клиент для работы с API Infersports
Основной источник данных о коэффициентах
"""

import aiohttp
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging

from config import config

logger = logging.getLogger(__name__)


class InfersportsClient:
    """Клиент для API Infersports"""
    
    def __init__(self):
        self.api_key = config.INFERSPORTS_API_KEY
        self.base_url = config.INFERSPORTS_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получение или создание HTTP сессии"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                }
            )
        return self.session
    
    async def close(self):
        """Закрытие сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def get_matches(self, hours_ahead: int = None) -> List[Dict[str, Any]]:
        """
        Получение списка матчей на ближайшие N часов
        
        Args:
            hours_ahead: На сколько часов вперед получать матчи
            
        Returns:
            Список матчей с коэффициентами
        """
        if hours_ahead is None:
            hours_ahead = config.MATCHES_HOURS_AHEAD
        
        session = await self._get_session()
        
        # Формируем временные рамки
        now = datetime.now()
        start_date = now.isoformat()
        end_date = (now + timedelta(hours=hours_ahead)).isoformat()
        
        try:
            # Запрос к API Infersports
            # Примечание: точный эндпоинт может отличаться в зависимости от API
            url = f"{self.base_url}/matches"
            params = {
                'start_date': start_date,
                'end_date': end_date,
                'sport': 'football',
                'include_odds': 'true'
            }
            
            logger.info(f"Запрос матчей с {start_date} по {end_date}")
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    matches = self._parse_matches(data)
                    logger.info(f"Получено {len(matches)} матчей")
                    return matches
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка API Infersports: {response.status} - {error_text}")
                    return []
                    
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка подключения к Infersports: {e}")
            return []
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении матчей: {e}")
            return []
    
    async def get_live_odds(self, match_id: str) -> Optional[Dict[str, Any]]:
        """
        Получение текущих коэффициентов для конкретного матча
        
        Args:
            match_id: ID матча
            
        Returns:
            Данные о коэффициентах или None
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/matches/{match_id}/odds"
            
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_odds(data)
                else:
                    logger.warning(f"Не удалось получить коэффициенты для матча {match_id}: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Ошибка при получении коэффициентов для матча {match_id}: {e}")
            return None
    
    async def get_all_current_odds(self, match_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Получение текущих коэффициентов для нескольких матчей
        
        Args:
            match_ids: Список ID матчей
            
        Returns:
            Словарь {match_id: odds_data}
        """
        results = {}
        
        # Ограничиваем количество одновременных запросов
        semaphore = asyncio.Semaphore(10)
        
        async def fetch_with_semaphore(match_id):
            async with semaphore:
                odds = await self.get_live_odds(match_id)
                if odds:
                    results[match_id] = odds
        
        tasks = [fetch_with_semaphore(mid) for mid in match_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        return results
    
    def _parse_matches(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Парсинг ответа API в стандартный формат
        
        Expected API response structure may vary, this is a generic parser
        """
        matches = []
        
        # Обработка разных форматов ответа
        if isinstance(data, dict):
            if 'matches' in data:
                raw_matches = data['matches']
            elif 'data' in data:
                raw_matches = data['data']
            else:
                raw_matches = [data]
        elif isinstance(data, list):
            raw_matches = data
        else:
            logger.warning(f"Неизвестный формат данных от API: {type(data)}")
            return []
        
        for match in raw_matches:
            try:
                parsed = {
                    'id': match.get('id') or match.get('match_id'),
                    'home_team': match.get('home_team') or match.get('homeTeam', {}).get('name', ''),
                    'away_team': match.get('away_team') or match.get('awayTeam', {}).get('name', ''),
                    'league': match.get('league') or match.get('tournament', {}).get('name', ''),
                    'start_time': match.get('start_time') or match.get('startTime') or match.get('date'),
                    'initial_coef_over': self._extract_over_coef(match),
                    'status': match.get('status', 'scheduled')
                }
                
                if parsed['id'] and parsed['home_team'] and parsed['away_team']:
                    matches.append(parsed)
                    
            except Exception as e:
                logger.warning(f"Ошибка парсинга матча: {e}")
                continue
        
        return matches
    
    def _extract_over_coef(self, match: Dict[str, Any]) -> float:
        """Извлечение коэффициента на ТБ (Тотал Больше)"""
        odds = match.get('odds', {})
        
        # Пробуем разные варианты структуры
        if isinstance(odds, dict):
            # Вариант 1: odds.over_2_5
            if 'over_2_5' in odds:
                return float(odds['over_2_5'])
            # Вариант 2: odds.over (для 2.5)
            if 'over' in odds:
                return float(odds['over'])
            # Вариант 3: odds.totals.over
            if 'totals' in odds and isinstance(odds['totals'], dict):
                if 'over' in odds['totals']:
                    return float(odds['totals']['over'])
            # Вариант 4: bookmakers -> 1XBet -> totals
            if 'bookmakers' in odds:
                for bookmaker in odds['bookmakers']:
                    if 'totals' in bookmaker:
                        for total in bookmaker['totals']:
                            if total.get('handicap') == 2.5 and total.get('type') == 'over':
                                return float(total.get('value', 0))
        
        # Если есть массив odds
        if isinstance(odds, list):
            for odd in odds:
                if odd.get('market') == 'totals' and odd.get('selection') == 'over':
                    if odd.get('handicap') == 2.5:
                        return float(odd.get('odds', 0))
        
        return 0.0
    
    def _parse_odds(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Парсинг данных о коэффициентах"""
        return {
            'over_coef': self._extract_over_coef(data),
            'under_coef': self._extract_under_coef(data),
            'timestamp': datetime.now().isoformat()
        }
    
    def _extract_under_coef(self, match: Dict[str, Any]) -> float:
        """Извлечение коэффициента на ТМ (Тотал Меньше)"""
        odds = match.get('odds', {})
        
        if isinstance(odds, dict):
            if 'under_2_5' in odds:
                return float(odds['under_2_5'])
            if 'under' in odds:
                return float(odds['under'])
            if 'totals' in odds and isinstance(odds['totals'], dict):
                if 'under' in odds['totals']:
                    return float(odds['totals']['under'])
        
        return 0.0


# Singleton instance
_infersports_client: Optional[InfersportsClient] = None


def get_infersports_client() -> InfersportsClient:
    """Получение singleton экземпляра клиента"""
    global _infersports_client
    if _infersports_client is None:
        _infersports_client = InfersportsClient()
    return _infersports_client
