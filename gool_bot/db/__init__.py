"""
Модуль работы с базой данных
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from config import config


@contextmanager
def get_connection():
    """Контекстный менеджер для подключения к БД"""
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Инициализация базы данных"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Таблица матчей с начальными коэффициентами
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                league TEXT,
                start_time DATETIME NOT NULL,
                initial_coef_over REAL NOT NULL,
                current_coef_over REAL,
                status TEXT DEFAULT 'scheduled',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица сигналов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                drop_percent REAL NOT NULL,
                initial_coef REAL NOT NULL,
                current_coef REAL NOT NULL,
                confirmed_by_highlightly BOOLEAN DEFAULT FALSE,
                highlightly_data TEXT,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        
        # Таблица результатов матчей (для статистики)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS match_results (
                match_id TEXT PRIMARY KEY,
                home_score INTEGER,
                away_score INTEGER,
                total_goals INTEGER,
                over_result BOOLEAN,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id)
            )
        """)
        
        # Таблица логов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Индексы для ускорения поиска
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_matches_start_time ON matches(start_time)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_match_id ON signals(match_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at)
        """)
        
        conn.commit()


def save_match(match_data: Dict[str, Any]):
    """Сохранение или обновление матча в БД"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO matches 
            (id, home_team, away_team, league, start_time, initial_coef_over, current_coef_over, status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            match_data['id'],
            match_data['home_team'],
            match_data['away_team'],
            match_data.get('league', ''),
            match_data['start_time'],
            match_data['initial_coef_over'],
            match_data.get('current_coef_over'),
            match_data.get('status', 'scheduled')
        ))
        conn.commit()


def get_all_matches() -> List[sqlite3.Row]:
    """Получение всех матчей из БД"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE status = 'scheduled' ORDER BY start_time")
        return cursor.fetchall()


def get_match(match_id: str) -> Optional[sqlite3.Row]:
    """Получение конкретного матча"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
        return cursor.fetchone()


def update_match_coef(match_id: str, current_coef: float):
    """Обновление текущего коэффициента матча"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE matches 
            SET current_coef_over = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (current_coef, match_id))
        conn.commit()


def save_signal(match_id: str, signal_type: str, drop_percent: float, 
                initial_coef: float, current_coef: float, 
                confirmed: bool = False, highlightly_data: str = None):
    """Сохранение сигнала в БД"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO signals 
            (match_id, signal_type, drop_percent, initial_coef, current_coef, confirmed_by_highlightly, highlightly_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (match_id, signal_type, drop_percent, initial_coef, current_coef, confirmed, highlightly_data))
        conn.commit()


def save_match_result(match_id: str, home_score: int, away_score: int, over_threshold: float = 2.5):
    """Сохранение результата матча"""
    total_goals = home_score + away_score
    over_result = total_goals > over_threshold
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO match_results 
            (match_id, home_score, away_score, total_goals, over_result)
            VALUES (?, ?, ?, ?, ?)
        """, (match_id, home_score, away_score, total_goals, over_result))
        
        # Обновляем статус матча
        cursor.execute("""
            UPDATE matches SET status = 'finished', updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """, (match_id,))
        
        conn.commit()


def cleanup_old_matches(days_old: int = 1):
    """Очистка старых матчей из БД"""
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Удаляем матчи, которые закончились больше чем days_old дней назад
        cursor.execute("""
            DELETE FROM matches 
            WHERE start_time < ? AND status = 'finished'
        """, (cutoff_date.isoformat(),))
        
        deleted_count = cursor.rowcount
        conn.commit()
        
        return deleted_count


def log_message(level: str, message: str):
    """Логирование сообщения в БД"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO logs (level, message) VALUES (?, ?)
        """, (level, message))
        conn.commit()


def get_recent_logs(limit: int = 100) -> List[sqlite3.Row]:
    """Получение последних логов"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM logs ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def get_signal_statistics() -> Dict[str, Any]:
    """Получение статистики по сигналам"""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Общее количество сигналов
        cursor.execute("SELECT COUNT(*) as total FROM signals")
        total_signals = cursor.fetchone()['total']
        
        # Сигналы по типам
        cursor.execute("""
            SELECT signal_type, COUNT(*) as count 
            FROM signals 
            GROUP BY signal_type
        """)
        by_type = {row['signal_type']: row['count'] for row in cursor.fetchall()}
        
        # Подтвержденные сигналы
        cursor.execute("""
            SELECT COUNT(*) as confirmed 
            FROM signals 
            WHERE confirmed_by_highlightly = TRUE
        """)
        confirmed = cursor.fetchone()['confirmed']
        
        return {
            'total': total_signals,
            'by_type': by_type,
            'confirmed': confirmed
        }


# Инициализация БД при импорте
init_db()
