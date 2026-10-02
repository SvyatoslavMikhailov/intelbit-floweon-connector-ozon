"""Тесты OzonOrdersClient — моки через respx."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from intelbit_floweon_connector_ozon.exceptions import OzonApiError
from intelbit_floweon_connector_ozon.orders import OzonOrdersClient
from intelbit_floweon_connector_ozon.rate_limiter import OzonRateLimiter
from tests.conftest import BASE_URL, load_mock

SINCE = datetime(2026, 5, 1, tzinfo=UTC)
UNTIL = datetime(2026, 5, 29, tzinfo=UTC)


@pytest.fixture
def orders(auth, fast_rate_limiter: OzonRateLimiter) -> OzonOrdersClient:
    return OzonOrdersClient(auth, BASE_URL, fast_rate_limiter)


@respx.mock
async def test_list_postings_happy(orders: OzonOrdersClient) -> None:
    respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(200, json=load_mock("orders/fbs_list_response.json"))
    )
    result = await orders.list_postings_fbs(since=SINCE)
    assert len(result.result) == 5
    assert result.has_next is True
    assert result.result[0].posting_number == "12345678-0001-1"


@respx.mock
async def test_list_parses_products(orders: OzonOrdersClient) -> None:
    respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(200, json=load_mock("orders/fbs_list_response.json"))
    )
    result = await orders.list_postings_fbs(since=SINCE)
    first = result.result[0]
    assert first.products[0].offer_id == "CF-001"
    assert first.products[0].quantity == 2


@respx.mock
async def test_list_sends_filter(orders: OzonOrdersClient) -> None:
    route = respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(200, json={"result": {"postings": [], "has_next": False}})
    )
    await orders.list_postings_fbs(since=SINCE, until=UNTIL, status="awaiting_deliver")
    body = json.loads(route.calls.last.request.content)
    assert body["filter"]["status"] == "awaiting_deliver"
    assert "since" in body["filter"] and "to" in body["filter"]
    assert body["with"] == {"analytics_data": True, "financial_data": True}


@respx.mock
async def test_list_sends_limit_offset(orders: OzonOrdersClient) -> None:
    route = respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(200, json={"result": {"postings": [], "has_next": False}})
    )
    await orders.list_postings_fbs(since=SINCE, limit=50, offset=100)
    body = json.loads(route.calls.last.request.content)
    assert body["limit"] == 50
    assert body["offset"] == 100


@respx.mock
async def test_get_posting(orders: OzonOrdersClient) -> None:
    respx.post(f"{BASE_URL}/v3/posting/fbs/get").mock(
        return_value=httpx.Response(200, json=load_mock("orders/fbs_get_response.json"))
    )
    posting = await orders.get_posting("12345678-0001-1")
    assert posting.tracking_number == "TRK-0001"
    assert len(posting.products) == 2


@respx.mock
async def test_ship_posting(orders: OzonOrdersClient) -> None:
    route = respx.post(f"{BASE_URL}/v3/posting/fbs/ship").mock(
        return_value=httpx.Response(200, json=load_mock("orders/ship_response.json"))
    )
    result = await orders.ship_posting("12345678-0001-1", packages=[{"products": []}])
    assert result["result"] == ["12345678-0001-1"]
    body = json.loads(route.calls.last.request.content)
    assert body["posting_number"] == "12345678-0001-1"


@respx.mock
async def test_update_status_cancelled_calls_cancel(orders: OzonOrdersClient) -> None:
    route = respx.post(f"{BASE_URL}/v3/posting/fbs/cancel").mock(
        return_value=httpx.Response(200, json={"result": True})
    )
    await orders.update_status("12345678-0005-1", "cancelled")
    assert route.called


@respx.mock
async def test_api_error_on_nonzero_code(orders: OzonOrdersClient) -> None:
    respx.post(f"{BASE_URL}/v3/posting/fbs/list").mock(
        return_value=httpx.Response(200, json={"code": 5, "message": "invalid filter"})
    )
    with pytest.raises(OzonApiError) as exc:
        await orders.list_postings_fbs(since=SINCE)
    assert exc.value.code == 5


@respx.mock
async def test_api_error_on_http_400(orders: OzonOrdersClient) -> None:
    respx.post(f"{BASE_URL}/v3/posting/fbs/get").mock(
        return_value=httpx.Response(400, json={"code": 3, "message": "not found"})
    )
    with pytest.raises(OzonApiError):
        await orders.get_posting("nope")


@respx.mock
async def test_auth_headers_sent(orders: OzonOrdersClient) -> None:
    route = respx.post(f"{BASE_URL}/v3/posting/fbs/get").mock(
        return_value=httpx.Response(200, json=load_mock("orders/fbs_get_response.json"))
    )
    await orders.get_posting("12345678-0001-1")
    headers = route.calls.last.request.headers
    assert headers["Client-Id"] == "12345"
    assert headers["Api-Key"] == "test-api-key"
