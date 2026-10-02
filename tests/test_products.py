"""Тесты OzonProductsClient + product-методы OzonConnector (моки respx)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.connector import OzonConnector
from intelbit_floweon_connector_ozon.exceptions import OzonApiError
from intelbit_floweon_connector_ozon.products import OzonProductsClient
from tests.conftest import BASE_URL, load_mock

LIST_PATH = f"{BASE_URL}/v2/product/list"
INFO_PATH = f"{BASE_URL}/v3/product/info/list"
ATTR_PATH = f"{BASE_URL}/v4/product/info/attributes"


@pytest.fixture
def products(auth, fast_rate_limiter) -> OzonProductsClient:
    return OzonProductsClient(OzonHttpClient(auth, BASE_URL, fast_rate_limiter))


@respx.mock
async def test_list_happy(products: OzonProductsClient) -> None:
    respx.post(LIST_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/list_page1.json"))
    )
    page = await products.list_products()
    assert len(page.items) == 100
    assert page.total == 150
    assert page.last_id == "abc"
    assert page.items[0].offer_id == "CF-0001"


@respx.mock
async def test_list_pagination_two_pages(products: OzonProductsClient) -> None:
    respx.post(LIST_PATH).mock(
        side_effect=[
            httpx.Response(200, json=load_mock("products/list_page1.json")),
            httpx.Response(200, json=load_mock("products/list_page2.json")),
        ]
    )
    page1 = await products.list_products()
    assert page1.last_id == "abc"
    page2 = await products.list_products(last_id=page1.last_id)
    assert len(page2.items) == 50
    assert page2.last_id == ""  # последняя страница


@respx.mock
async def test_list_visibility_filter(products: OzonProductsClient) -> None:
    route = respx.post(LIST_PATH).mock(
        return_value=httpx.Response(200, json={"result": {"items": [], "total": 0, "last_id": ""}})
    )
    await products.list_products(visibility="VISIBLE", limit=10)
    body = json.loads(route.calls.last.request.content)
    assert body["filter"]["visibility"] == "VISIBLE"
    assert body["limit"] == 10


@respx.mock
async def test_get_info_by_offer_ids(products: OzonProductsClient) -> None:
    route = respx.post(INFO_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/info_batch_5_items.json"))
    )
    infos = await products.get_info_batch(offer_ids=["CF-0001", "CF-0002"])
    assert len(infos) == 5
    body = json.loads(route.calls.last.request.content)
    assert body["offer_id"] == ["CF-0001", "CF-0002"]
    assert body["product_id"] == []


@respx.mock
async def test_get_info_by_product_ids(products: OzonProductsClient) -> None:
    route = respx.post(INFO_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/info_batch_5_items.json"))
    )
    await products.get_info_batch(product_ids=[555001, 555002])
    body = json.loads(route.calls.last.request.content)
    assert body["product_id"] == [555001, 555002]
    assert body["offer_id"] == []


@respx.mock
async def test_get_info_auto_split_over_1000(products: OzonProductsClient) -> None:
    route = respx.post(INFO_PATH).mock(
        return_value=httpx.Response(200, json={"result": {"items": []}})
    )
    offer_ids = [f"X-{i}" for i in range(1500)]
    await products.get_info_batch(offer_ids=offer_ids)
    assert route.call_count == 2  # 1000 + 500


@respx.mock
async def test_get_info_api_error(products: OzonProductsClient) -> None:
    respx.post(INFO_PATH).mock(
        return_value=httpx.Response(200, json={"code": 6, "message": "invalid offer_id"})
    )
    with pytest.raises(OzonApiError) as exc:
        await products.get_info_batch(offer_ids=["BAD"])
    assert exc.value.code == 6


async def test_get_info_requires_ids(products: OzonProductsClient) -> None:
    with pytest.raises(ValueError, match="хотя бы один"):
        await products.get_info_batch()


@respx.mock
async def test_info_parses_images_and_dimensions(products: OzonProductsClient) -> None:
    respx.post(INFO_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/info_batch_5_items.json"))
    )
    infos = await products.get_info_batch(offer_ids=["CF-0001"])
    first = next(i for i in infos if i.offer_id == "CF-0001")
    assert first.primary_image == "https://cdn1.ozone.ru/cf-0001-main.jpg"
    assert len(first.images) == 2
    assert first.images[0].default is True
    assert first.weight == 800 and first.height == 150
    assert first.barcodes == ["4600000000017", "4600000000018"]
    # картинки как объекты (CF-0002) тоже парсятся
    second = next(i for i in infos if i.offer_id == "CF-0002")
    assert second.images[1].file_name == "https://cdn1.ozone.ru/cf-0002-2.jpg"


@respx.mock
async def test_get_attributes_happy_multi_value(products: OzonProductsClient) -> None:
    respx.post(ATTR_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/attributes_batch.json"))
    )
    page = await products.get_attributes_batch(offer_ids=["CF-0001", "CF-0002", "CF-0003"])
    assert len(page.items) == 3
    cf2 = next(a for a in page.items if a.offer_id == "CF-0002")
    color = next(attr for attr in cf2.attributes if attr.name == "Цвет")
    assert [v.value for v in color.values] == ["Бежевый", "Молочный"]


@respx.mock
async def test_get_attributes_pagination_last_id(products: OzonProductsClient) -> None:
    route = respx.post(ATTR_PATH).mock(
        return_value=httpx.Response(200, json={"result": [], "last_id": "next-cursor"})
    )
    page = await products.get_attributes_batch(offer_ids=["CF-0001"], last_id="prev", limit=50)
    assert page.last_id == "next-cursor"
    body = json.loads(route.calls.last.request.content)
    assert body["last_id"] == "prev"
    assert body["limit"] == 50


@respx.mock
async def test_connector_product_methods(auth) -> None:
    connector = OzonConnector(
        config={
            "client_id": "12345",
            "api_key": "test-api-key",
            "base_url": BASE_URL,
            "rate_limits": {"default_rps": 1000.0, "per_second": {}},
        }
    )
    respx.post(LIST_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/list_page1.json"))
    )
    respx.post(INFO_PATH).mock(
        return_value=httpx.Response(200, json=load_mock("products/info_batch_5_items.json"))
    )
    page = await connector.list_products(limit=100)
    assert len(page["items"]) == 100

    infos = await connector.get_products_info(["CF-0001", "CF-0002"])
    assert isinstance(infos, list)
    assert infos[0]["offer_id"] == "CF-0001"
