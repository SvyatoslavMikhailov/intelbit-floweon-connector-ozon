"""Общие фикстуры тестов коннектора Ozon."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from intelbit_floweon_connector_ozon.auth import OzonAuth
from intelbit_floweon_connector_ozon.rate_limiter import OzonRateLimiter, OzonRateLimiterConfig

BASE_URL = "https://api-seller.ozon.ru"
_FIXTURES = Path(__file__).parent / "fixtures" / "ozon-mocks"


def load_mock(relative: str) -> dict[str, Any]:
    """Загрузить JSON-фикстуру мока Ozon (путь относительно fixtures/ozon-mocks/)."""
    return json.loads((_FIXTURES / relative).read_text(encoding="utf-8"))


@pytest.fixture
def auth() -> OzonAuth:
    return OzonAuth(client_id="12345", api_key="test-api-key")


@pytest.fixture
def fast_rate_limiter() -> OzonRateLimiter:
    """Высокие лимиты — чтобы rate limiting не тормозил unit-тесты клиентов."""
    return OzonRateLimiter(OzonRateLimiterConfig(default_rps=1000.0, per_second={}))
