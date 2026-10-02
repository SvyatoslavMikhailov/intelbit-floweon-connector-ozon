"""Тесты OzonStocksClient — моки через respx."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from intelbit_floweon_connector_ozon.exceptions import OzonApiError
from intelbit_floweon_connector_ozon.models import StockUpdate
from intelbit_floweon_connector_ozon.stocks import OzonStocksClient
from tests.conftest import BASE_URL, load_mock

STOCKS_PATH = f"{BASE_URL}/v1/product/info/stocks-by-warehouse/fbs"


@pytest.fixture
def stocks(auth, fast_rate_limiter) -> OzonStocksClient:
    return OzonStocksClient(auth, BASE_URL, fast_rate_limiter)


@respx.mock
async def test_update_single(stocks: OzonStocksClient) -> None:
    respx.post(STOCKS_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("stocks/update_stocks_response.json"))
    )
    result = await stocks.update_stocks(
        [StockUpdate(product_id=555001, stock=100, warehouse_id=22222)]
    )
    assert len(result.result) == 2
    assert result.result[0].updated is True


@respx.mock
async def test_update_reports_per_item_error(stocks: OzonStocksClient) -> None:
    respx.post(STOCKS_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("stocks/update_stocks_response.json"))
    )
    result = await stocks.update_stocks(
        [StockUpdate(product_id=555002, stock=0, warehouse_id=22222)]
    )
    failed = result.result[1]
    assert failed.updated is False
    assert failed.errors[0]["code"] == "INVALID_STATE"


@respx.mock
async def test_update_batch_over_100_splits(stocks: OzonStocksClient) -> None:
    route = respx.post(STOCKS_PATH).mock(return_value=httpx.Response(200, json={"result": []}))
    updates = [StockUpdate(product_id=i, stock=1, warehouse_id=22222) for i in range(250)]
    await stocks.update_stocks(updates)
    # 250 → 3 чанка (100+100+50)
    assert route.call_count == 3
    last_body = json.loads(route.calls[-1].request.content)
    assert len(last_body["stocks"]) == 50


@respx.mock
async def test_update_body_shape(stocks: OzonStocksClient) -> None:
    route = respx.post(STOCKS_PATH).mock(return_value=httpx.Response(200, json={"result": []}))
    await stocks.update_stocks([StockUpdate(product_id=1, stock=7, warehouse_id=9, offer_id="X-1")])
    item = json.loads(route.calls.last.request.content)["stocks"][0]
    assert item == {"product_id": 1, "stock": 7, "warehouse_id": 9, "offer_id": "X-1"}


@respx.mock
async def test_get_stocks(stocks: OzonStocksClient) -> None:
    respx.post(f"{BASE_URL}/v2/product/info/stocks").mock(
        return_value=httpx.Response(200, json=load_mock("stocks/get_stocks_response.json"))
    )
    result = await stocks.get_stocks([555001, 555002])
    assert result[0].present == 120
    assert result[0].reserved == 5
    assert result[1].offer_id == "FD-010"


@respx.mock
async def test_get_stocks_empty_list(stocks: OzonStocksClient) -> None:
    respx.post(f"{BASE_URL}/v2/product/info/stocks").mock(
        return_value=httpx.Response(200, json={"result": {"items": []}})
    )
    assert await stocks.get_stocks([]) == []


@respx.mock
async def test_update_api_error(stocks: OzonStocksClient) -> None:
    respx.post(STOCKS_PATH).mock(
        return_value=httpx.Response(200, json={"code": 8, "message": "bad warehouse"})
    )
    with pytest.raises(OzonApiError):
        await stocks.update_stocks([StockUpdate(product_id=1, stock=1, warehouse_id=0)])
