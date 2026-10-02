"""OzonStocksClient — push остатков по складам FBS + чтение остатков."""

from __future__ import annotations

from typing import Any

from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.models import (
    StockInfo,
    StockUpdate,
    StockUpdateItemResult,
    UpdateStocksResult,
)

_MAX_BATCH = 100


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class OzonStocksClient(OzonHttpClient):
    """Клиент остатков Ozon Seller API."""

    async def update_stocks(self, stocks: list[StockUpdate]) -> UpdateStocksResult:
        """POST /v1/product/info/stocks-by-warehouse/fbs — обновить остатки.

        Batch до 100 за вызов; больше — режем на чанки и шлём последовательно.
        """
        merged: list[StockUpdateItemResult] = []
        for chunk in _chunks(stocks, _MAX_BATCH):
            payload = {"stocks": [s.to_ozon() for s in chunk]}
            data = await self._post("/v1/product/info/stocks-by-warehouse/fbs", payload)
            for item in data.get("result", []):
                merged.append(
                    StockUpdateItemResult(
                        product_id=item.get("product_id", 0),
                        offer_id=item.get("offer_id", ""),
                        warehouse_id=item.get("warehouse_id", 0),
                        updated=item.get("updated", False),
                        errors=item.get("errors", []),
                    )
                )
        return UpdateStocksResult(result=merged)

    async def get_stocks(self, product_ids: list[int]) -> list[StockInfo]:
        """POST /v2/product/info/stocks — текущие остатки по product_id."""
        payload = {"filter": {"product_id": product_ids}, "limit": len(product_ids) or 1}
        data = await self._post("/v2/product/info/stocks", payload)
        items = data.get("result", {}).get("items", [])
        result: list[StockInfo] = []
        for item in items:
            stocks = item.get("stocks", [{}])
            first = stocks[0] if stocks else {}
            result.append(
                StockInfo(
                    product_id=item.get("product_id", 0),
                    offer_id=item.get("offer_id", ""),
                    present=first.get("present", 0),
                    reserved=first.get("reserved", 0),
                )
            )
        return result
