"""
Клиент для работы с API Highlightly
Вторичный источник для подтверждения сигналов
"""

import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging

from config import config

logger = logging.getLogger(__name__)


class HighlightlyClient:
    """Клиент для API Highlightly"""
    
    def __init__(self):
        self.api_key = config.HIGHLIGHTLY_API_KEY
        self.base_url = config.HIGHLIGHTLY_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
        self.request_count = 0
        self.rate_limit_remaining = None
    
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
    
    async def get_match_analysis(self, home_team: str, away_team: str) -> Optional[Dict[str, Any]]:
        """
        Получение аналитики матча от Highlightly
        
        Args:
            home_team: Название домашней команды
            away_team: Название гостевой команды
            
        Returns:
            Данные аналитики или None
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/match/analysis"
            params = {
                'home_team': home_team,
                'away_team': away_team,
                'sport': 'football'
            }
            
            logger.info(f"Запрос аналитики для матча: {home_team} vs {away_team}")
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self._update_rate_limit(response.headers)
                    return self._parse_analysis(data)
                elif response.status == 429:
                    logger.warning("Превышен лимит запросов к Highlightly API")
                    self._update_rate_limit(response.headers)
                    return None
                else:
                    error_text = await response.text()
                    logger.warning(f"Ошибка API Highlightly: {response.status} - {error_text}")
                    return None
                    
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка подключения к Highlightly: {e}")
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при получении аналитики: {e}")
            return None
    
    async def get_h2h_stats(self, team1: str, team2: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получение истории личных встреч (H2H)
        
        Args:
            team1: Первая команда
            team2: Вторая команда
            limit: Количество последних встреч
            
        Returns:
            Список матчей H2H
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/h2h"
            params = {
                'team1': team1,
                'team2': team2,
                'limit': limit
            }
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self._update_rate_limit(response.headers)
                    return data.get('matches', [])
                else:
                    logger.warning(f"Не удалось получить H2H статистику: {response.status}")
                    return []
                    
        except Exception as e:
            logger.error(f"Ошибка при получении H2H статистики: {e}")
            return []
    
    async def get_team_form(self, team_name: str, matches_count: int = 5) -> Optional[Dict[str, Any]]:
        """
        Получение текущей формы команды
        
        Args:
            team_name: Название команды
            matches_count: Количество последних матчей для анализа
            
        Returns:
            Данные о форме команды
        """
        session = await self._get_session()
        
        try:
            url = f"{self.base_url}/team/{team_name}/form"
            params = {
                'matches': matches_count
            }
            
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    self._update_rate_limit(response.headers)
                    return self._parse_team_form(data)
                else:
                    logger.warning(f"Не удалось получить форму команды {team_name}: {response.status}")
                    return None
                    
        except Exception as e:
            logger.error(f"Ошибка при получении формы команды: {e}")
            return None
    
    async def get_average_goals(self, team1: str, team2: str) -> Dict[str, float]:
        """
        Получение среднего количества голов для команд
        
        Args:
            team1: Первая команда
            team2: Вторая команда
            
        Returns:
            Словарь со средней статистикой голов
        """
        form1 = await self.get_team_form(team1)
        form2 = await self.get_team_form(team2)
        
        result = {
            'team1_avg_scored': 0.0,
            'team1_avg_conceded': 0.0,
            'team2_avg_scored': 0.0,
            'team2_avg_conceded': 0.0,
            'combined_avg': 0.0
        }
        
        if form1:
            result['team1_avg_scored'] = form1.get('avg_goals_scored', 0.0)
            result['team1_avg_conceded'] = form1.get('avg_goals_conceded', 0.0)
        
        if form2:
            result['team2_avg_scored'] = form2.get('avg_goals_scored', 0.0)
            result['team2_avg_conceded'] = form2.get('avg_goals_conceded', 0.0)
        
        # Общий средний тотал
        total_avg = (
            result['team1_avg_scored'] + result['team1_avg_conceded'] +
            result['team2_avg_scored'] + result['team2_avg_conceded']
        ) / 2
        result['combined_avg'] = total_avg
        
        return result
    
    def _update_rate_limit(self, headers: dict):
        """Обновление информации о лимитах API"""
        self.rate_limit_remaining = headers.get('X-RateLimit-Remaining')
        self.request_count += 1
    
    def _parse_analysis(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Парсинг данных аналитики"""
        return {
            'h2h_matches': data.get('h2h', []),
            'team1_form': data.get('home_team_form', {}),
            'team2_form': data.get('away_team_form', {}),
            'avg_goals': data.get('average_goals', {}),
            'prediction': data.get('prediction', {}),
            'confidence': data.get('confidence', 0.0),
            'recommendation': data.get('recommendation', '')
        }
    
    def _parse_team_form(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Парсинг данных о форме команды"""
        recent_matches = data.get('recent_matches', [])
        
        goals_scored = [m.get('goals_scored', 0) for m in recent_matches]
        goals_conceded = [m.get('goals_conceded', 0) for m in recent_matches]
        
        avg_scored = sum(goals_scored) / len(goals_scored) if goals_scored else 0.0
        avg_conceded = sum(goals_conceded) / len(goals_conceded) if goals_conceded else 0.0
        
        return {
            'avg_goals_scored': avg_scored,
            'avg_goals_conceded': avg_conceded,
            'wins': sum(1 for m in recent_matches if m.get('result') == 'W'),
            'draws': sum(1 for m in recent_matches if m.get('result') == 'D'),
            'losses': sum(1 for m in recent_matches if m.get('result') == 'L'),
            'total_matches': len(recent_matches)
        }
    
    def is_rate_limited(self) -> bool:
        """Проверка, исчерпан ли лимит запросов"""
        # Если осталось меньше 5 запросов, считаем что лимит почти исчерпан
        if self.rate_limit_remaining is not None:
            return int(self.rate_limit_remaining) < 5
        return False


# Singleton instance
_highlightly_client: Optional[HighlightlyClient] = None


def get_highlightly_client() -> HighlightlyClient:
    """Получение singleton экземпляра клиента"""
    global _highlightly_client
    if _highlightly_client is None:
        _highlightly_client = HighlightlyClient()
    return _highlightly_client
