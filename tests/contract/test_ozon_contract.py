"""End-to-end contract-тесты: OzonConnector ↔ FastAPI-мок Ozon Seller API.

Запуск: uv run pytest -m contract -v
"""

from __future__ import annotations

import json

import pytest

from intelbit_floweon_connector_ozon.connector import OzonConnector

pytestmark = pytest.mark.contract


async def test_list_fbs_postings(connector: OzonConnector) -> None:
    """Сценарий 1: list_orders → 5 postings корректных типов."""
    orders = await connector.list_orders(since="2026-05-01T00:00:00+00:00")
    assert len(orders) == 5
    assert orders[0]["posting_number"] == "12345678-0001-1"
    assert orders[0]["products"][0]["offer_id"] == "CF-001"


async def test_update_stocks_batch_split(connector: OzonConnector) -> None:
    """Сценарий 2: 250 позиций → 3 batch (100/100/50), все успешны."""
    stocks = [{"product_id": i, "stock": 10, "warehouse_id": 22222} for i in range(250)]
    result = await connector.update_stocks(stocks)
    assert len(result["result"]) == 250
    assert all(item["updated"] for item in result["result"])


async def test_update_prices(connector: OzonConnector) -> None:
    """Сценарий 3: update_prices с old_price/min_price → корректный echo от мока."""
    prices = [
        {
            "product_id": 555001,
            "price": "1790.00",
            "old_price": "1990.00",
            "min_price": "1500.00",
        }
    ]
    result = await connector.update_prices(prices)
    assert result["result"][0]["product_id"] == 555001
    assert result["result"][0]["updated"] is True


async def test_webhook_new_posting_with_dedup(connector: OzonConnector) -> None:
    """Сценарий 4: on_webhook TYPE_NEW_POSTING → parse + dedup через Redis."""
    body = json.dumps(
        {
            "message_type": "TYPE_NEW_POSTING",
            "message_id": "msg-contract-1",
            "posting_number": "12345678-0001-1",
            "warehouse_id": 22222,
            "products": [{"sku": 123451, "quantity": 1}],
        }
    ).encode()

    first = await connector.on_webhook({}, body)
    assert first["message_type"] == "TYPE_NEW_POSTING"
    assert first["duplicate"] is False

    second = await connector.on_webhook({}, body)
    assert second["duplicate"] is True  # повтор пойман дедупом


async def test_rate_limit_retry(connector: OzonConnector) -> None:
    """Сценарий 5: 7 вызовов подряд — 6-й HTTP получит 429, retry после Retry-After успешен."""
    results = []
    for _ in range(7):
        results.append(await connector.list_orders(since="2026-05-01T00:00:00+00:00"))
    # Если бы 429 не ретраился — здесь был бы OzonRateLimitError.
    assert all(len(r) == 5 for r in results)
