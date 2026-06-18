"""
SQLite-based FSM Storage — Bot restart bo'lsa ham state'lar saqlanadi

MemoryStorage o'rniga ishlatiladi.
"""
import json
import logging
from typing import Any, Dict, Optional

import aiosqlite
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey, StateType

logger = logging.getLogger(__name__)


class SQLiteStorage(BaseStorage):
    """
    SQLite-based FSM storage.
    
    Bot restart bo'lganda ham foydalanuvchilarning holati (state)
    va ma'lumotlari (data) saqlanib qoladi.
    """
    
    def __init__(self, db_path: str = "data/fsm_storage.sqlite3"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
    
    async def _get_db(self) -> aiosqlite.Connection:
        """Database connectionni olish yoki yaratish"""
        if self._db is None:
            self._db = await aiosqlite.connect(self.db_path, check_same_thread=False)
            await self._db.execute('PRAGMA journal_mode=WAL')
            await self._db.execute('PRAGMA synchronous=NORMAL')
            
            await self._db.execute('''
                CREATE TABLE IF NOT EXISTS fsm_states (
                    key TEXT PRIMARY KEY,
                    state TEXT,
                    data TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await self._db.commit()
            logger.info("SQLiteStorage initialized")
        
        return self._db
    
    def _make_key(self, key: StorageKey) -> str:
        """StorageKey'ni string ga o'girish"""
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}"
    
    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        """State'ni saqlash"""
        db = await self._get_db()
        str_key = self._make_key(key)
        state_str = state.state if isinstance(state, State) else state
        
        await db.execute('''
            INSERT INTO fsm_states (key, state, data, updated_at)
            VALUES (?, ?, '{}', CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET state = ?, updated_at = CURRENT_TIMESTAMP
        ''', (str_key, state_str, state_str))
        await db.commit()
    
    async def get_state(self, key: StorageKey) -> Optional[str]:
        """State'ni olish"""
        db = await self._get_db()
        str_key = self._make_key(key)
        
        async with db.execute(
            'SELECT state FROM fsm_states WHERE key = ?', (str_key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
    
    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        """Data'ni saqlash"""
        db = await self._get_db()
        str_key = self._make_key(key)
        data_json = json.dumps(data, ensure_ascii=False, default=str)
        
        await db.execute('''
            INSERT INTO fsm_states (key, state, data, updated_at)
            VALUES (?, NULL, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET data = ?, updated_at = CURRENT_TIMESTAMP
        ''', (str_key, data_json, data_json))
        await db.commit()
    
    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        """Data'ni olish"""
        db = await self._get_db()
        str_key = self._make_key(key)
        
        async with db.execute(
            'SELECT data FROM fsm_states WHERE key = ?', (str_key,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    return {}
            return {}
    
    async def update_data(self, key: StorageKey, data: Dict[str, Any]) -> Dict[str, Any]:
        """Data'ni yangilash (merge)"""
        current = await self.get_data(key)
        current.update(data)
        await self.set_data(key, current)
        return current
    
    async def close(self) -> None:
        """Connectionni yopish"""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("SQLiteStorage closed")
    
    async def cleanup_old_states(self, hours: int = 72):
        """72 soatdan eski state'larni tozalash"""
        db = await self._get_db()
        result = await db.execute('''
            DELETE FROM fsm_states 
            WHERE updated_at < datetime('now', ?)
        ''', (f'-{hours} hours',))
        await db.commit()
        
        if result.rowcount > 0:
            logger.info(f"Cleaned up {result.rowcount} old FSM states")
