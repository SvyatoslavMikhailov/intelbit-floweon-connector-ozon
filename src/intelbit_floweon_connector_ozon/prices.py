"""OzonPricesClient — push цен (old_price/min_price/auto_action) + чтение цен."""

from __future__ import annotations

from typing import Any

from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.models import (
    PriceInfo,
    PriceUpdate,
    PriceUpdateItemResult,
    UpdatePricesResult,
)

_MAX_BATCH = 1000


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class OzonPricesClient(OzonHttpClient):
    """Клиент цен Ozon Seller API."""

    async def update_prices(self, prices: list[PriceUpdate]) -> UpdatePricesResult:
        """POST /v1/product/import/prices — обновить цены. Batch до 1000 за вызов."""
        merged: list[PriceUpdateItemResult] = []
        for chunk in _chunks(prices, _MAX_BATCH):
            payload = {"prices": [p.to_ozon() for p in chunk]}
            data = await self._post("/v1/product/import/prices", payload)
            for item in data.get("result", []):
                merged.append(
                    PriceUpdateItemResult(
                        product_id=item.get("product_id", 0),
                        offer_id=item.get("offer_id", ""),
                        updated=item.get("updated", False),
                        errors=item.get("errors", []),
                    )
                )
        return UpdatePricesResult(result=merged)

    async def get_prices(self, product_ids: list[int]) -> list[PriceInfo]:
        """POST /v4/product/info/prices — текущие цены по product_id."""
        payload = {
            "filter": {"product_id": [str(pid) for pid in product_ids], "visibility": "ALL"},
            "limit": len(product_ids) or 1,
        }
        data = await self._post("/v4/product/info/prices", payload)
        items = data.get("result", {}).get("items", [])
        result: list[PriceInfo] = []
        for item in items:
            price = item.get("price", {})
            result.append(
                PriceInfo(
                    product_id=item.get("product_id", 0),
                    offer_id=item.get("offer_id", ""),
                    price=str(price.get("price", "0")),
                    old_price=str(price.get("old_price", "0")),
                    min_price=str(price.get("min_price", "0")),
                    currency_code=price.get("currency_code", "RUB"),
                )
            )
        return result
