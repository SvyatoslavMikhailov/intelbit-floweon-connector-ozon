"""End-to-end тесты OzonConnector через композицию клиентов (моки respx)."""

from __future__ import annotations

import fakeredis.aioredis
import httpx
import pytest
import respx

from intelbit_floweon_connector_ozon.connector import OzonConnector
from intelbit_floweon_connector_ozon.exceptions import ConfigurationError, WebhookValidationError
from tests.conftest import BASE_URL, TEST_WEBHOOK_SECRET, load_mock, signed_body


@pytest.fixture
def connector() -> OzonConnector:
    return OzonConnector(
        config={
            "client_id": "12345",
            "api_key": "test-api-key",
            "base_url": BASE_URL,
            "rate_limits": {"default_rps": 1000.0, "per_second": {}},
            "webhook": {"secret": TEST_WEBHOOK_SECRET},
        }
    )


@respx.mock
async def test_list_orders_end_to_end(connector: OzonConnector) -> None:
    respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(200, json=load_mock("orders/fbs_list_response.json"))
    )
    orders = await connector.list_orders(since="2026-05-01T00:00:00+00:00")
    assert isinstance(orders, list)
    assert len(orders) == 5
    assert orders[0]["posting_number"] == "12345678-0001-1"  # JSON-сериализуемый dict


@respx.mock
async def test_update_stocks_via_connector(connector: OzonConnector) -> None:
    respx.post(f"{BASE_URL}/v1/product/info/stocks-by-warehouse/fbs").mock(
        return_value=httpx.Response(200, json=load_mock("stocks/update_stocks_response.json"))
    )
    result = await connector.update_stocks(
        [{"product_id": 555001, "stock": 100, "warehouse_id": 22222}]
    )
    assert result["result"][0]["updated"] is True


@respx.mock
async def test_update_prices_via_connector(connector: OzonConnector) -> None:
    respx.post(f"{BASE_URL}/v1/product/import/prices").mock(
        return_value=httpx.Response(200, json=load_mock("prices/update_prices_response.json"))
    )
    result = await connector.update_prices(
        [{"product_id": 555001, "price": "1790.00", "old_price": "1990.00"}]
    )
    assert len(result["result"]) == 2


async def test_on_webhook_ping_handled(connector: OzonConnector) -> None:
    body = signed_body(load_mock("webhooks/ping.json"))
    result = await connector.on_webhook({}, body)
    assert result == {"result": True}


async def test_on_webhook_new_posting_parsed(connector: OzonConnector) -> None:
    body = signed_body(load_mock("webhooks/new_posting.json"))
    result = await connector.on_webhook({}, body)
    assert result["message_type"] == "TYPE_NEW_POSTING"
    assert result["posting_number"] == "12345678-0001-1"


async def test_on_webhook_dedup_with_redis() -> None:
    connector = OzonConnector(
        config={
            "client_id": "1",
            "api_key": "k",
            "redis_client": fakeredis.aioredis.FakeRedis(),
            "webhook": {"secret": TEST_WEBHOOK_SECRET},
        }
    )
    body = signed_body(load_mock("webhooks/new_posting.json"))
    first = await connector.on_webhook({}, body)
    second = await connector.on_webhook({}, body)
    assert first["duplicate"] is False
    assert second["duplicate"] is True


async def test_health_check(connector: OzonConnector) -> None:
    assert await connector.health_check() is True


class TestOzonAuth:
    def test_headers(self) -> None:
        from intelbit_floweon_connector_ozon.auth import OzonAuth

        auth = OzonAuth(client_id="12345", api_key="secret-key")
        headers = auth.headers()
        assert headers["Client-Id"] == "12345"
        assert headers["Api-Key"] == "secret-key"
        assert headers["Content-Type"] == "application/json"


def test_connector_without_webhook_secret_raises() -> None:
    """Fail-closed: приём вебхуков включён по умолчанию, без секрета коннектор не стартует."""
    with pytest.raises(ConfigurationError, match=r"webhook\.secret"):
        OzonConnector(config={"client_id": "1", "api_key": "k"})


def test_connector_webhooks_disabled_starts_without_secret() -> None:
    connector = OzonConnector(
        config={"client_id": "1", "api_key": "k", "webhook": {"enabled": False}}
    )
    assert connector.webhooks.enabled is False


async def test_on_webhook_disabled_rejects() -> None:
    connector = OzonConnector(
        config={"client_id": "1", "api_key": "k", "webhook": {"enabled": False}}
    )
    with pytest.raises(WebhookValidationError):
        await connector.on_webhook({}, signed_body(load_mock("webhooks/ping.json")))


async def test_on_webhook_passes_peer_ip_to_allowlist() -> None:
    connector = OzonConnector(
        config={
            "client_id": "1",
            "api_key": "k",
            "webhook": {"secret": TEST_WEBHOOK_SECRET, "allowed_ips": ["1.2.3.4"]},
        }
    )
    body = signed_body(load_mock("webhooks/ping.json"))
    assert await connector.on_webhook({}, body, peer_ip="1.2.3.4") == {"result": True}
    with pytest.raises(WebhookValidationError):
        await connector.on_webhook({}, body, peer_ip="9.9.9.9")
