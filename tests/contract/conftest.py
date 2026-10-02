"""Фикстуры contract-тестов: свежий мок Ozon + ASGITransport на каждый тест."""

from __future__ import annotations

import fakeredis.aioredis
import httpx
import pytest

from intelbit_floweon_connector_ozon.connector import OzonConnector
from tests.conftest import TEST_WEBHOOK_SECRET
from tests.mock_ozon_server.main import create_app

MOCK_BASE_URL = "http://mock-ozon"


@pytest.fixture
def ozon_mock_transport() -> httpx.ASGITransport:
    """Свежее мок-приложение (изолированные счётчики 429) через ASGITransport."""
    return httpx.ASGITransport(app=create_app())


@pytest.fixture
def connector(ozon_mock_transport: httpx.ASGITransport) -> OzonConnector:
    return OzonConnector(
        config={
            "client_id": "12345",
            "api_key": "test-api-key",
            "base_url": MOCK_BASE_URL,
            "transport": ozon_mock_transport,
            # Высокий клиентский лимит — 429 приходит от мок-сервера, не от token bucket.
            "rate_limits": {"default_rps": 1000.0, "per_second": {}, "max_retries": 3},
            "redis_client": fakeredis.aioredis.FakeRedis(),
            "webhook": {"secret": TEST_WEBHOOK_SECRET},
        }
    )
