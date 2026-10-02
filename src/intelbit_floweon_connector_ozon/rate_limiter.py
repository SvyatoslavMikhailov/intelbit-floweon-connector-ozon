"""Учёт RPS-лимитов Ozon Seller API — token bucket per-endpoint."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from pydantic import BaseModel, Field

# Дефолтные per-second лимиты по докам Ozon (RPS). Ключ — путь endpoint.
_DEFAULT_RPS: dict[str, float] = {
    "/v3/posting/fbs/list": 5.0,
    "/v3/posting/fbs/get": 10.0,
    "/v3/posting/fbs/ship": 5.0,
    "/v1/product/import/prices": 10.0,
    "/v4/product/info/prices": 10.0,
    "/v1/product/info/stocks-by-warehouse/fbs": 80.0,
    "/v2/product/info/stocks": 10.0,
}


class OzonRateLimiterConfig(BaseModel):
    """Конфигурация лимитов. По умолчанию — известные методы Ozon."""

    default_rps: float = 10.0
    per_second: dict[str, float] = Field(default_factory=lambda: dict(_DEFAULT_RPS))
    max_retries: int = 3


class TokenBucket:
    """Классический token bucket.

    capacity — максимум токенов; refill_rate — токенов/сек. Токены пополняются
    непрерывно по времени. try_acquire не блокирует; time_until_available
    сообщает, сколько ждать до появления нужного числа токенов.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._time = time_func
        self.tokens = capacity
        self.last_refill_at = time_func()

    def _refill(self) -> None:
        now = self._time()
        elapsed = now - self.last_refill_at
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill_at = now

    def try_acquire(self, count: float = 1.0) -> bool:
        self._refill()
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False

    def time_until_available(self, count: float = 1.0) -> float:
        self._refill()
        if self.tokens >= count:
            return 0.0
        deficit = count - self.tokens
        return deficit / self.refill_rate


class OzonRateLimiter:
    """Per-endpoint rate limiting с async-ожиданием квоты."""

    def __init__(
        self,
        config: OzonRateLimiterConfig | None = None,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config or OzonRateLimiterConfig()
        self._time = time_func
        self._buckets: dict[str, TokenBucket] = {}

    def _bucket(self, method: str) -> TokenBucket:
        bucket = self._buckets.get(method)
        if bucket is None:
            rps = self._config.per_second.get(method, self._config.default_rps)
            # capacity = rps: допускаем всплеск до лимита за секунду.
            bucket = TokenBucket(capacity=rps, refill_rate=rps, time_func=self._time)
            self._buckets[method] = bucket
        return bucket

    async def acquire(self, method: str) -> None:
        """Дождаться токена для метода (асинхронно, без busy-wait)."""
        bucket = self._bucket(method)
        while not bucket.try_acquire():
            wait = bucket.time_until_available()
            if wait <= 0:
                continue
            await asyncio.sleep(wait)

    @property
    def max_retries(self) -> int:
        return self._config.max_retries
