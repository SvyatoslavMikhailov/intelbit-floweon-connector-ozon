"""Smoke-тест enrich_vitrina: respx-мок Ozon + FastAPI ASGI-мок БУС.

3 товара Ozon, 2 совпадают с элементами БУС по XML_ID, 1 — нет.
Проверяем dry-run (только CSV) и apply (запись в мок БУС).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
import respx
from _vitrina_client import VitrinaBusClient
from enrich_vitrina import build_parser, run_enrichment
from fastapi import FastAPI, Request

from intelbit_river_connector_ozon.connector import OzonConnector

OZON = "https://api-seller.ozon.ru"
BITRIX = "http://bitrix/rest/0/test-token"

_OZON_LIST = {
    "result": {
        "items": [
            {"product_id": 1, "offer_id": "A1"},
            {"product_id": 2, "offer_id": "A2"},
            {"product_id": 3, "offer_id": "A3"},
        ],
        "total": 3,
        "last_id": "",
    }
}
_OZON_INFO = {
    "result": {
        "items": [
            {
                "id": 1,
                "offer_id": "A1",
                "name": "P1",
                "description": "Описание A1",
                "images": ["https://cdn.test/a1-1.jpg", "https://cdn.test/a1-2.jpg"],
            },
            {
                "id": 2,
                "offer_id": "A2",
                "name": "P2",
                "description": "Описание A2",
                "images": [{"file_name": "https://cdn.test/a2.jpg", "default": True}],
            },
            {"id": 3, "offer_id": "A3", "name": "P3"},
        ]
    }
}
_OZON_ATTRS = {
    "result": [
        {
            "id": 1,
            "offer_id": "A1",
            "attributes": [
                {"attribute_id": 85, "name": "Бренд", "values": [{"value": "Care Friend"}]}
            ],
        },
        {"id": 2, "offer_id": "A2", "attributes": []},
        {"id": 3, "offer_id": "A3", "attributes": []},
    ],
    "last_id": "",
}


def _make_bitrix_app() -> tuple[FastAPI, dict[str, list[Any]]]:
    """Мок БУС: scope `catalog`, тело form-urlencoded (как реальный webhook)."""
    app = FastAPI()
    calls: dict[str, list[Any]] = {"update": [], "upload": []}

    async def _form(request: Request) -> dict[str, str]:
        # form-urlencoded без python-multipart: парсим тело сами
        return dict(parse_qsl((await request.body()).decode("utf-8")))

    @app.post("/rest/0/test-token/catalog.product.list.json")
    async def product_list(request: Request) -> dict[str, Any]:
        form = await _form(request)
        if int(form.get("start", "0") or "0") > 0:
            return {"result": {"products": []}}
        return {
            "result": {
                "products": [
                    {"id": 101, "iblockId": 5, "name": "Товар 1", "xmlId": "A1", "code": "a1"},
                    {"id": 102, "iblockId": 5, "name": "Товар 2", "xmlId": "A2", "code": "a2"},
                    {"id": 103, "iblockId": 5, "name": "Прочее", "xmlId": "OTHER", "code": "o"},
                ]
            }
        }

    @app.post("/rest/0/test-token/catalog.productProperty.list.json")
    async def property_list(request: Request) -> dict[str, Any]:
        return {
            "result": {
                "productProperties": [
                    {"id": 25, "code": "MORE_PHOTO", "iblockId": 5},
                    {"id": 26, "code": "OZON_BREND", "iblockId": 5},
                ]
            }
        }

    @app.post("/rest/0/test-token/catalog.productImage.add.json")
    async def image_add(request: Request) -> dict[str, Any]:
        calls["upload"].append(await _form(request))
        return {"result": {"productImage": {"id": 9000 + len(calls["upload"])}}}

    @app.post("/rest/0/test-token/catalog.product.update.json")
    async def product_update(request: Request) -> dict[str, Any]:
        form = await _form(request)
        calls["update"].append(form)
        return {"result": {"element": {"id": form.get("id")}}}

    return app, calls


def _args(*extra: str) -> Any:
    return build_parser().parse_args(
        ["--vitrina-iblock-id", "5", "--vitrina-storage-id", "7", *extra]
    )


def _mock_ozon() -> None:
    respx.post(f"{OZON}/v2/product/list").mock(return_value=httpx.Response(200, json=_OZON_LIST))
    respx.post(f"{OZON}/v3/product/info/list").mock(
        return_value=httpx.Response(200, json=_OZON_INFO)
    )
    respx.post(f"{OZON}/v4/product/info/attributes").mock(
        return_value=httpx.Response(200, json=_OZON_ATTRS)
    )
    for url in (
        "https://cdn.test/a1-1.jpg",
        "https://cdn.test/a1-2.jpg",
        "https://cdn.test/a2.jpg",
    ):
        respx.get(url).mock(return_value=httpx.Response(200, content=b"\xff\xd8imgbytes"))


def _build(transport: httpx.ASGITransport) -> tuple[OzonConnector, VitrinaBusClient]:
    ozon = OzonConnector(
        {
            "client_id": "x",
            "api_key": "y",
            "base_url": OZON,
            "rate_limits": {"default_rps": 1000.0, "per_second": {}},
        }
    )
    vitrina = VitrinaBusClient(BITRIX, iblock_id=5, storage_id=7, _transport=transport)
    return ozon, vitrina


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@respx.mock
async def test_dry_run(tmp_path: Path) -> None:
    _mock_ozon()
    app, calls = _make_bitrix_app()
    transport = httpx.ASGITransport(app=app)
    ozon, vitrina = _build(transport)
    try:
        counts = await run_enrichment(ozon, vitrina, _args(), tmp_path)
    finally:
        await vitrina.aclose()

    assert counts == {"matched": 2, "skipped": 1, "errors": 0}
    assert len(_read_csv(tmp_path / "matched.csv")) == 2
    assert len(_read_csv(tmp_path / "skipped.csv")) == 1
    assert len(_read_csv(tmp_path / "errors.csv")) == 0
    # dry-run в БУС не пишет
    assert calls["update"] == []
    assert calls["upload"] == []


@respx.mock
async def test_apply(tmp_path: Path) -> None:
    _mock_ozon()
    app, calls = _make_bitrix_app()
    transport = httpx.ASGITransport(app=app)
    ozon, vitrina = _build(transport)
    try:
        counts = await run_enrichment(ozon, vitrina, _args("--apply"), tmp_path)
    finally:
        await vitrina.aclose()

    assert counts == {"matched": 2, "skipped": 1, "errors": 0}
    # A1 (2 картинки) + A2 (1 картинка) → 3 catalog.productImage.add
    assert len(calls["upload"]) == 3
    # catalog.product.update вызван для обоих matched
    assert len(calls["update"]) == 2
    updated_ids = {str(c["id"]) for c in calls["update"]}
    assert updated_ids == {"101", "102"}
    # A1 имеет бренд → характеристика OZON_BREND (property26) ушла в update
    assert any(
        any(k.startswith("fields[property26]") for k in c) for c in calls["update"]
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Цвет", "CVET"), ("Бренд", "BREND"), ("Вес, г", "VES_G")],
)
def test_slugify(name: str, expected: str) -> None:
    from enrich_vitrina import slugify_property_code

    assert slugify_property_code(name) == expected
