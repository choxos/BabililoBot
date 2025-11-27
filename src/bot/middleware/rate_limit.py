"""Rate limiting middleware using token bucket algorithm."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict

from src.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    """Token bucket for rate limiting."""

    capacity: int
    tokens: float = field(default=0.0)
    last_update: float = field(default_factory=time.time)
    refill_rate: float = 1.0  # tokens per second

    def __post_init__(self):
        self.tokens = float(self.capacity)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_update = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if not enough tokens
        """
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def time_until_available(self, tokens: int = 1) -> float:
        """Calculate time until tokens are available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Seconds until tokens are available
        """
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        needed = tokens - self.tokens
        return needed / self.refill_rate


class RateLimiter:
    """Rate limiter for bot users."""

    def __init__(self):
        self.settings = get_settings()
        self._buckets: Dict[int, TokenBucket] = {}
        self._lock = asyncio.Lock()

        # Calculate refill rate from settings
        # rate_limit_messages per rate_limit_window_seconds
        self.capacity = self.settings.rate_limit_messages
        self.refill_rate = self.capacity / self.settings.rate_limit_window_seconds

    def _get_bucket(self, user_id: int) -> TokenBucket:
        """Get or create token bucket for user."""
        if user_id not in self._buckets:
            self._buckets[user_id] = TokenBucket(
                capacity=self.capacity,
                refill_rate=self.refill_rate,
            )
        return self._buckets[user_id]

    async def check_rate_limit(self, user_id: int, is_admin: bool = False) -> tuple[bool, float]:
        """Check if user is within rate limit.

        Args:
            user_id: User's Telegram ID
            is_admin: Whether user is an admin (admins have higher limits)

        Returns:
            Tuple of (allowed, wait_time)
        """
        async with self._lock:
            # Admins get 5x the normal rate limit
            if is_admin:
                # Use a separate bucket for admins or just allow
                return True, 0.0

            bucket = self._get_bucket(user_id)

            if bucket.consume(1):
                return True, 0.0

            wait_time = bucket.time_until_available(1)
            return False, wait_time

    async def reset_user(self, user_id: int) -> None:
        """Reset rate limit for a user.

        Args:
            user_id: User's Telegram ID
        """
        async with self._lock:
            if user_id in self._buckets:
                del self._buckets[user_id]

    async def cleanup_old_buckets(self, max_age_seconds: int = 3600) -> int:
        """Clean up old buckets to prevent memory leaks.

        Args:
            max_age_seconds: Remove buckets not used in this many seconds

        Returns:
            Number of buckets cleaned up
        """
        async with self._lock:
            now = time.time()
            old_buckets = [
                user_id
                for user_id, bucket in self._buckets.items()
                if now - bucket.last_update > max_age_seconds
            ]

            for user_id in old_buckets:
                del self._buckets[user_id]

            if old_buckets:
                logger.debug(f"Cleaned up {len(old_buckets)} old rate limit buckets")

            return len(old_buckets)

    def get_stats(self) -> dict:
        """Get rate limiter statistics.

        Returns:
            Dict with stats
        """
        return {
            "active_buckets": len(self._buckets),
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
        }

