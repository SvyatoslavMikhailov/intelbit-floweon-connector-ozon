"""Тесты OzonPricesClient — моки через respx."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from intelbit_floweon_connector_ozon.exceptions import OzonApiError
from intelbit_floweon_connector_ozon.models import PriceUpdate
from intelbit_floweon_connector_ozon.prices import OzonPricesClient
from tests.conftest import BASE_URL, load_mock

PRICES_PATH = f"{BASE_URL}/v1/product/import/prices"


@pytest.fixture
def prices(auth, fast_rate_limiter) -> OzonPricesClient:
    return OzonPricesClient(auth, BASE_URL, fast_rate_limiter)


@respx.mock
async def test_update_with_old_and_min_price(prices: OzonPricesClient) -> None:
    route = respx.post(PRICES_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("prices/update_prices_response.json"))
    )
    result = await prices.update_prices(
        [
            PriceUpdate(
                product_id=555001,
                price="1790.00",
                old_price="1990.00",
                min_price="1500.00",
                auto_action_enabled="ENABLED",
            )
        ]
    )
    assert result.result[0].updated is True
    item = json.loads(route.calls.last.request.content)["prices"][0]
    assert item["old_price"] == "1990.00"
    assert item["min_price"] == "1500.00"
    assert item["auto_action_enabled"] == "ENABLED"


@respx.mock
async def test_update_minimal_body_omits_empty(prices: OzonPricesClient) -> None:
    route = respx.post(PRICES_PATH).mock(return_value=httpx.Response(200, json={"result": []}))
    await prices.update_prices([PriceUpdate(product_id=1, price="100.00")])
    item = json.loads(route.calls.last.request.content)["prices"][0]
    assert "old_price" not in item
    assert "min_price" not in item
    assert item["currency_code"] == "RUB"


@respx.mock
async def test_update_batch_over_1000_splits(prices: OzonPricesClient) -> None:
    route = respx.post(PRICES_PATH).mock(return_value=httpx.Response(200, json={"result": []}))
    updates = [PriceUpdate(product_id=i, price="10.00") for i in range(2300)]
    await prices.update_prices(updates)
    # 2300 → 3 чанка (1000+1000+300)
    assert route.call_count == 3
    assert len(json.loads(route.calls[-1].request.content)["prices"]) == 300


@respx.mock
async def test_get_prices(prices: OzonPricesClient) -> None:
    respx.post(f"{BASE_URL}/v4/product/info/prices").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "items": [
                        {
                            "product_id": 555001,
                            "offer_id": "CF-001",
                            "price": {
                                "price": "1790.00",
                                "old_price": "1990.00",
                                "min_price": "1500.00",
                                "currency_code": "RUB",
                            },
                        }
                    ]
                }
            },
        )
    )
    result = await prices.get_prices([555001])
    assert result[0].price == "1790.00"
    assert result[0].old_price == "1990.00"


@respx.mock
async def test_update_api_error(prices: OzonPricesClient) -> None:
    respx.post(PRICES_PATH).mock(
        return_value=httpx.Response(200, json={"code": 7, "message": "price too low"})
    )
    with pytest.raises(OzonApiError) as exc:
        await prices.update_prices([PriceUpdate(product_id=1, price="1.00")])
    assert exc.value.code == 7
