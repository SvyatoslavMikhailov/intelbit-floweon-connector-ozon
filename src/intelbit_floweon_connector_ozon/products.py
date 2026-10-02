"""OzonProductsClient — каталог Ozon (list / info / attributes) для ETL-обогащения.

Композиция над OzonHttpClient (rate-limit + 429-backoff + разбор ошибок уже там).
"""

from __future__ import annotations

from typing import Any

from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.product_models import (
    AttributesPage,
    OzonAttributeValue,
    OzonImage,
    OzonProductAttribute,
    OzonProductAttributes,
    OzonProductInfo,
    ProductListItem,
    ProductListPage,
)

_INFO_MAX_BATCH = 1000


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _parse_image(raw: Any, index: int) -> OzonImage:
    if isinstance(raw, str):
        return OzonImage(file_name=raw, default=index == 0, index=index)
    return OzonImage(
        file_name=raw.get("file_name", ""),
        default=bool(raw.get("default", index == 0)),
        index=raw.get("index", index),
    )


def _parse_info(raw: dict[str, Any]) -> OzonProductInfo:
    primary = raw.get("primary_image")
    if isinstance(primary, list):
        primary = primary[0] if primary else None
    images = [_parse_image(img, i) for i, img in enumerate(raw.get("images", []))]
    return OzonProductInfo(
        product_id=raw.get("id") or raw.get("product_id", 0),
        offer_id=raw.get("offer_id", ""),
        name=raw.get("name", ""),
        description=raw.get("description"),
        barcode=raw.get("barcode"),
        barcodes=raw.get("barcodes", []) or [],
        primary_image=primary,
        images=images,
        weight=raw.get("weight"),
        depth=raw.get("depth"),
        width=raw.get("width"),
        height=raw.get("height"),
    )


def _parse_attributes(raw: dict[str, Any]) -> OzonProductAttributes:
    attrs = [
        OzonProductAttribute(
            id=a.get("attribute_id") or a.get("id", 0),
            name=a.get("name", ""),
            values=[
                OzonAttributeValue(
                    dictionary_value_id=v.get("dictionary_value_id"),
                    value=str(v.get("value", "")),
                )
                for v in a.get("values", [])
            ],
        )
        for a in raw.get("attributes", [])
    ]
    return OzonProductAttributes(
        id=raw.get("id") or raw.get("product_id", 0),
        offer_id=raw.get("offer_id", ""),
        attributes=attrs,
    )


class OzonProductsClient:
    """Клиент каталога Ozon Seller API."""

    def __init__(self, http: OzonHttpClient) -> None:
        self._http = http

    async def list_products(
        self, last_id: str = "", limit: int = 1000, visibility: str = "ALL"
    ) -> ProductListPage:
        """POST /v2/product/list — cursor-пагинация через last_id (пустой → конец)."""
        payload = {"filter": {"visibility": visibility}, "last_id": last_id, "limit": limit}
        data = await self._http.post("/v2/product/list", payload)
        result = data.get("result", {})
        items = [
            ProductListItem(
                product_id=it.get("product_id", 0),
                offer_id=it.get("offer_id", ""),
                has_fbo_stocks=it.get("has_fbo_stocks"),
                has_fbs_stocks=it.get("has_fbs_stocks"),
                archived=it.get("archived"),
            )
            for it in result.get("items", [])
        ]
        return ProductListPage(
            items=items, total=result.get("total", 0), last_id=result.get("last_id", "")
        )

    async def get_info_batch(
        self,
        offer_ids: list[str] | None = None,
        product_ids: list[int] | None = None,
    ) -> list[OzonProductInfo]:
        """POST /v3/product/info/list — детали товаров. Batch ≤1000 с auto-split."""
        offer_ids = offer_ids or []
        product_ids = product_ids or []
        if not offer_ids and not product_ids:
            raise ValueError("get_info_batch: нужен хотя бы один из offer_ids / product_ids")

        # Чанкуем по тому идентификатору, который передан (оба сразу — редкий кейс).
        offer_chunks = _chunks(offer_ids, _INFO_MAX_BATCH) or [[]]
        product_chunks = _chunks(product_ids, _INFO_MAX_BATCH) or [[]]
        chunks = offer_chunks if offer_ids else product_chunks

        result: list[OzonProductInfo] = []
        for chunk in chunks:
            payload = {
                "offer_id": chunk if offer_ids else [],
                "product_id": [] if offer_ids else chunk,
            }
            data = await self._http.post("/v3/product/info/list", payload)
            raw = data.get("result", {})
            items = raw.get("items", raw) if isinstance(raw, dict) else raw
            result.extend(_parse_info(it) for it in items)
        return result

    async def get_attributes_batch(
        self,
        offer_ids: list[str] | None = None,
        product_ids: list[int] | None = None,
        last_id: str = "",
        limit: int = 100,
    ) -> AttributesPage:
        """POST /v4/product/info/attributes — характеристики товаров (с пагинацией)."""
        payload = {
            "filter": {
                "offer_id": offer_ids or [],
                "product_id": product_ids or [],
                "visibility": "ALL",
            },
            "last_id": last_id,
            "limit": limit,
        }
        data = await self._http.post("/v4/product/info/attributes", payload)
        raw = data.get("result", [])
        items = raw.get("items", []) if isinstance(raw, dict) else raw
        return AttributesPage(
            items=[_parse_attributes(it) for it in items],
            last_id=data.get("last_id", "")
            or (raw.get("last_id", "") if isinstance(raw, dict) else ""),
        )
