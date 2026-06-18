"""
Rate Limiter — Brute-force himoyasi

Login, parol kiritish kabi operatsiyalar uchun
urinishlar sonini cheklash.
"""
import time
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    In-memory rate limiter.
    
    Foydalanish:
        limiter = RateLimiter(max_attempts=5, block_duration=900)
        
        allowed, info = limiter.check(user_id)
        if not allowed:
            # Bloklangan
            ...
        
        # Muvaffaqiyatsiz urinish
        limiter.record_failure(user_id)
        
        # Muvaffaqiyatli — resetlash
        limiter.reset(user_id)
    """
    
    def __init__(self, max_attempts: int = 5, block_duration: int = 900):
        """
        Args:
            max_attempts: Maksimal urinishlar soni
            block_duration: Block vaqti (sekundlarda), default 15 daqiqa
        """
        self.max_attempts = max_attempts
        self.block_duration = block_duration
        self._attempts: Dict[int, list] = {}  # {user_id: [timestamp, ...]}
        self._blocked: Dict[int, float] = {}  # {user_id: blocked_until_timestamp}
    
    def check(self, user_id: int) -> Tuple[bool, str]:
        """
        Foydalanuvchi ruxsat etilganmi tekshirish.
        
        Returns:
            (allowed, info_message)
        """
        now = time.time()
        
        # Bloklangan bo'lsa
        if user_id in self._blocked:
            blocked_until = self._blocked[user_id]
            if now < blocked_until:
                remaining = int(blocked_until - now)
                minutes = remaining // 60
                seconds = remaining % 60
                return False, f"{minutes} daqiqa {seconds} soniya"
            else:
                # Block muddati tugagan
                del self._blocked[user_id]
                if user_id in self._attempts:
                    del self._attempts[user_id]
        
        return True, ""
    
    def record_failure(self, user_id: int) -> Tuple[bool, int]:
        """
        Muvaffaqiyatsiz urinishni qayd etish.
        
        Returns:
            (is_now_blocked, remaining_attempts)
        """
        now = time.time()
        
        if user_id not in self._attempts:
            self._attempts[user_id] = []
        
        # Eski urinishlarni tozalash (block_duration ichidagilar)
        self._attempts[user_id] = [
            t for t in self._attempts[user_id]
            if now - t < self.block_duration
        ]
        
        self._attempts[user_id].append(now)
        
        attempt_count = len(self._attempts[user_id])
        remaining = self.max_attempts - attempt_count
        
        if attempt_count >= self.max_attempts:
            # Bloklash
            self._blocked[user_id] = now + self.block_duration
            logger.warning(
                f"User {user_id} blocked for {self.block_duration}s "
                f"after {attempt_count} failed login attempts"
            )
            return True, 0
        
        return False, remaining
    
    def reset(self, user_id: int):
        """Muvaffaqiyatli login — urinishlarni tozalash"""
        self._attempts.pop(user_id, None)
        self._blocked.pop(user_id, None)
    
    def get_remaining_attempts(self, user_id: int) -> int:
        """Qolgan urinishlar soni"""
        if user_id not in self._attempts:
            return self.max_attempts
        
        now = time.time()
        recent = [t for t in self._attempts[user_id] if now - t < self.block_duration]
        return max(0, self.max_attempts - len(recent))
    
    def cleanup(self):
        """Eskirgan yozuvlarni tozalash (xotira uchun)"""
        now = time.time()
        
        # Expired blocks
        expired_blocks = [
            uid for uid, until in self._blocked.items()
            if now >= until
        ]
        for uid in expired_blocks:
            del self._blocked[uid]
        
        # Old attempts
        expired_attempts = [
            uid for uid, attempts in self._attempts.items()
            if not any(now - t < self.block_duration for t in attempts)
        ]
        for uid in expired_attempts:
            del self._attempts[uid]


# Global login limiter: 5 ta urinish, 15 daqiqa block
login_limiter = RateLimiter(max_attempts=5, block_duration=900)

# Admin password limiter: 3 ta urinish, 30 daqiqa block
admin_password_limiter = RateLimiter(max_attempts=3, block_duration=1800)
