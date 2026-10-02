"""OzonOrdersClient — заказы FBS: список, детали, отгрузка."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.models import OzonPosting, PostingProduct, PostingsList


def _iso(dt: datetime) -> str:
    """datetime → ISO-8601 в формате, который ждёт Ozon (Z-суффикс UTC)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_posting(raw: dict[str, Any]) -> OzonPosting:
    """Сырое отправление Ozon → OzonPosting (терпимо к отсутствующим полям)."""
    products = [
        PostingProduct(
            sku=p.get("sku", 0),
            name=p.get("name", ""),
            offer_id=p.get("offer_id", ""),
            quantity=p.get("quantity", 0),
            price=str(p.get("price", "0")),
            currency_code=p.get("currency_code", "RUB"),
        )
        for p in raw.get("products", [])
    ]
    return OzonPosting(
        posting_number=raw["posting_number"],
        order_id=raw.get("order_id", 0),
        order_number=raw.get("order_number", ""),
        status=raw.get("status", "awaiting_packaging"),
        created_at=raw.get("in_process_at") or raw.get("created_at", ""),
        in_process_at=raw.get("in_process_at", ""),
        products=products,
        tracking_number=raw.get("tracking_number", ""),
        warehouse_id=raw.get("warehouse_id", 0),
    )


class OzonOrdersClient(OzonHttpClient):
    """Клиент заказов FBS Ozon Seller API."""

    async def list_postings_fbs(
        self,
        since: datetime,
        until: datetime | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PostingsList:
        """POST /v3/posting/fbs/list — страница FBS-отправлений за период."""
        filter_body: dict[str, Any] = {"since": _iso(since)}
        if until is not None:
            filter_body["to"] = _iso(until)
        if status:
            filter_body["status"] = status

        payload = {
            "filter": filter_body,
            "limit": limit,
            "offset": offset,
            "with": {"analytics_data": True, "financial_data": True},
        }
        data = await self._post("/v3/posting/fbs/list", payload)
        result = data.get("result", {})
        postings = [_parse_posting(p) for p in result.get("postings", [])]
        return PostingsList(result=postings, has_next=result.get("has_next", False))

    async def get_posting(self, posting_number: str) -> OzonPosting:
        """POST /v3/posting/fbs/get — детали одного отправления."""
        payload = {
            "posting_number": posting_number,
            "with": {"analytics_data": True, "financial_data": True},
        }
        data = await self._post("/v3/posting/fbs/get", payload)
        return _parse_posting(data.get("result", {}))

    async def ship_posting(
        self, posting_number: str, packages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """POST /v3/posting/fbs/ship — собрать и передать отправление в доставку."""
        payload = {"posting_number": posting_number, "packages": packages}
        return await self._post("/v3/posting/fbs/ship", payload)

    async def update_status(self, posting_number: str, status: str) -> dict[str, Any]:
        """Смена статуса. У Ozon нет универсального status-update: cancelled → cancel,
        иначе ship. Прочие статусы Ozon выставляет сам по ходу доставки."""
        if status == "cancelled":
            payload = {"posting_number": posting_number, "cancel_reason_id": 352}
            return await self._post("/v3/posting/fbs/cancel", payload)
        return await self.ship_posting(posting_number, packages=[])
