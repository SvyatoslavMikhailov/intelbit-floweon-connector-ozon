"""Тесты OzonRateLimiter / TokenBucket и 429-backoff в HTTP-слое."""

from __future__ import annotations

import httpx
import pytest
import respx

from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.exceptions import OzonRateLimitError
from intelbit_floweon_connector_ozon.rate_limiter import (
    OzonRateLimiter,
    OzonRateLimiterConfig,
    TokenBucket,
)
from tests.conftest import BASE_URL


class FakeClock:
    """Управляемые часы для детерминизма token bucket."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def test_bucket_consume() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=5, refill_rate=5, time_func=clock)
    for _ in range(5):
        assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False  # исчерпан


def test_bucket_time_until_available() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=2, refill_rate=2, time_func=clock)
    bucket.try_acquire()
    bucket.try_acquire()
    # пусто; refill_rate=2/сек → 1 токен через 0.5с
    assert bucket.time_until_available() == pytest.approx(0.5)


def test_bucket_refills_over_time() -> None:
    clock = FakeClock()
    bucket = TokenBucket(capacity=10, refill_rate=10, time_func=clock)
    for _ in range(10):
        bucket.try_acquire()
    assert bucket.try_acquire() is False
    clock.advance(1.0)  # +10 токенов (но capacity=10)
    assert bucket.try_acquire() is True


def test_per_method_limits() -> None:
    limiter = OzonRateLimiter()
    fast = limiter._bucket("/v1/product/info/stocks-by-warehouse/fbs")
    slow = limiter._bucket("/v3/posting/fbs/list")
    unknown = limiter._bucket("/some/unknown")
    assert fast.capacity == 80.0
    assert slow.capacity == 5.0
    assert unknown.capacity == 10.0  # default_rps


async def test_acquire_returns_when_tokens_available() -> None:
    limiter = OzonRateLimiter(OzonRateLimiterConfig(default_rps=100.0, per_second={}))
    await limiter.acquire("/any")  # не виснет, токены есть


@respx.mock
async def test_429_retry_after_then_success(auth) -> None:
    limiter = OzonRateLimiter(OzonRateLimiterConfig(default_rps=1000.0, per_second={}))
    client = OzonHttpClient(auth, BASE_URL, limiter)
    respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"result": {"postings": [], "has_next": False}}),
        ]
    )
    data = await client._post("/v3/posting/fbs/list", {})
    assert data["result"]["has_next"] is False


@respx.mock
async def test_429_exhausted_raises(auth) -> None:
    config = OzonRateLimiterConfig(default_rps=1000.0, per_second={}, max_retries=2)
    limiter = OzonRateLimiter(config)
    client = OzonHttpClient(auth, BASE_URL, limiter)
    respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "0"})
    )
    with pytest.raises(OzonRateLimitError):
        await client._post("/v3/posting/fbs/list", {})
