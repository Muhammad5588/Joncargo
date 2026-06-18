"""
Admin Audit Log — Admin harakatlari tarixi

Barcha admin amallarini (approve, reject, delete, edit, broadcast)
loglash va kuzatish.
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict

import pytz

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")


class AuditLogger:
    """Admin harakatlarini DB va log faylga yozish"""
    
    def __init__(self, db):
        self.db = db
        self._initialized = False
    
    async def initialize(self):
        """Audit log jadvalini yaratish"""
        if self._initialized:
            return
        
        async with self.db.get_connection() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT,
                    target_id TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_audit_admin ON audit_log(admin_id)'
            )
            await conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)'
            )
            await conn.execute(
                'CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)'
            )
            await conn.commit()
        
        self._initialized = True
        logger.info("Audit log table initialized")
    
    async def log(
        self,
        admin_id: int,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[str] = None
    ):
        """
        Admin harakatini loglash
        
        Args:
            admin_id: Admin Telegram ID
            action: Harakat turi (approve, reject, delete, edit, broadcast, ...)
            target_type: Maqsad turi (user, channel, settings, ...)
            target_id: Maqsad ID
            details: Qo'shimcha ma'lumot
        """
        await self.initialize()
        
        try:
            await self.db.execute('''
                INSERT INTO audit_log (admin_id, action, target_type, target_id, details)
                VALUES (?, ?, ?, ?, ?)
            ''', (admin_id, action, target_type, str(target_id) if target_id else None, details))
            
            logger.info(
                f"AUDIT: admin={admin_id} action={action} "
                f"target={target_type}:{target_id} details={details}"
            )
        except Exception as e:
            logger.error(f"Audit log error: {e}")
    
    async def get_recent_logs(self, limit: int = 50) -> List[Dict]:
        """Oxirgi loglarni olish"""
        await self.initialize()
        
        import aiosqlite
        async with self.db.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute('''
                SELECT * FROM audit_log
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_admin_logs(self, admin_id: int, limit: int = 20) -> List[Dict]:
        """Bitta admin loglarini olish"""
        await self.initialize()
        
        import aiosqlite
        async with self.db.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute('''
                SELECT * FROM audit_log
                WHERE admin_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (admin_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_user_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        """Bitta foydalanuvchi tarixi"""
        await self.initialize()
        
        import aiosqlite
        async with self.db.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute('''
                SELECT * FROM audit_log
                WHERE target_id = ? AND target_type = 'user'
                ORDER BY created_at DESC
                LIMIT ?
            ''', (str(user_id), limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def close(self):
        """Cleanup (DB connection audit_log o'zi boshqarmaydi)"""
        self._initialized = False


# Global instance — data_db bilan ishlaydi
from data.Async_sqlDataBase import data_db
audit_logger = AuditLogger(data_db)