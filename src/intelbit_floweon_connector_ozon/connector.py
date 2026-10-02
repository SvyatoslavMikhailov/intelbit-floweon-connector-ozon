"""OzonConnector — коннектор Ozon Seller API для Интелбит.Фловеон (ADR-006).

Реальная композиция Orders/Stocks/Prices/Webhooks поверх общего auth +
rate_limiter. Методы idempotent: read-only (list_orders) — естественно;
write (update_stocks/update_prices) — Ozon idempotent в рамках payload;
on_webhook — дедуп через Redis (если передан redis_client).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from intelbit_floweon_connector_ozon.auth import OzonAuth
from intelbit_floweon_connector_ozon.base import OzonHttpClient
from intelbit_floweon_connector_ozon.models import PingEvent, PriceUpdate, StockUpdate
from intelbit_floweon_connector_ozon.orders import OzonOrdersClient
from intelbit_floweon_connector_ozon.prices import OzonPricesClient
from intelbit_floweon_connector_ozon.products import OzonProductsClient
from intelbit_floweon_connector_ozon.rate_limiter import OzonRateLimiter, OzonRateLimiterConfig
from intelbit_floweon_connector_ozon.stocks import OzonStocksClient
from intelbit_floweon_connector_ozon.webhooks import OzonWebhookReceiver


class OzonConnector:
    """Коннектор Ozon Seller API (FBS-сценарий)."""

    BASE_URL = "https://api-seller.ozon.ru"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        base_url = config.get("base_url", self.BASE_URL)

        self._auth = OzonAuth(
            client_id=str(config["client_id"]),
            api_key=str(config["api_key"]),
        )
        rate_cfg = config.get("rate_limits")
        rate_limiter = OzonRateLimiter(OzonRateLimiterConfig(**rate_cfg) if rate_cfg else None)

        # transport — только для contract-тестов (httpx.ASGITransport на мок Ozon).
        transport = config.get("transport")
        self.orders = OzonOrdersClient(self._auth, base_url, rate_limiter, transport)
        self.stocks = OzonStocksClient(self._auth, base_url, rate_limiter, transport)
        self.prices = OzonPricesClient(self._auth, base_url, rate_limiter, transport)
        self.products = OzonProductsClient(
            OzonHttpClient(self._auth, base_url, rate_limiter, transport)
        )
        # Fail-closed: без webhook.secret (при webhook.enabled, default true) —
        # ConfigurationError здесь, на инициализации.
        self.webhooks = OzonWebhookReceiver(config.get("webhook"))
        self._redis_client = config.get("redis_client")

    async def list_orders(self, since: str, status: str | None = None) -> list[dict[str, Any]]:
        """Список FBS-заказов с момента since (ISO-8601)."""
        since_dt = datetime.fromisoformat(since)
        postings = await self.orders.list_postings_fbs(since=since_dt, status=status)
        return [p.model_dump(mode="json") for p in postings.result]

    async def ship_order(
        self, posting_number: str, packages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Отгрузить заказ."""
        return await self.orders.ship_posting(posting_number, packages)

    async def update_stocks(self, stocks: list[dict[str, Any]]) -> dict[str, Any]:
        """Push остатков. Принимает список dict (JSON-IPC)."""
        parsed = [StockUpdate(**s) for s in stocks]
        result = await self.stocks.update_stocks(parsed)
        return result.model_dump(mode="json")

    async def update_prices(self, prices: list[dict[str, Any]]) -> dict[str, Any]:
        """Push цен. Принимает список dict (JSON-IPC)."""
        parsed = [PriceUpdate(**p) for p in prices]
        result = await self.prices.update_prices(parsed)
        return result.model_dump(mode="json")

    async def on_webhook(
        self, headers: dict[str, str], body: bytes, peer_ip: str | None = None
    ) -> dict[str, Any]:
        """Обработать входящий webhook: валидация → парсинг → PING/событие.

        peer_ip — адрес TCP-собеседника (из HTTP-сервера, например
        ``request.client.host``); нужен для IP-allowlist и ``trusted_proxies``.
        """
        self.webhooks.verify_request(headers, body, peer_ip=peer_ip)
        event = self.webhooks.parse_event(body)
        if isinstance(event, PingEvent):
            return self.webhooks.respond_ping(event)

        payload: dict[str, Any] = event.model_dump(mode="json")
        if self._redis_client is not None and event.message_id:
            payload["duplicate"] = await self.webhooks.deduplicate(
                event.message_id, self._redis_client
            )
        return payload

    async def health_check(self) -> bool:
        """Доступность коннектора: учётные данные настроены."""
        return bool(self._auth.client_id and self._auth.api_key)

    # ------------------------------------------------------------------ #
    # Каталог Ozon — admin/ETL операции (не часть обязательного ConnectorPlugin).
    # ------------------------------------------------------------------ #

    async def list_products(self, last_id: str = "", limit: int = 1000) -> dict[str, Any]:
        """Страница каталога Ozon (cursor-пагинация через last_id)."""
        page = await self.products.list_products(last_id=last_id, limit=limit)
        return page.model_dump(mode="json")

    async def get_products_info(self, offer_ids: list[str]) -> list[dict[str, Any]]:
        """Детали товаров по offer_id (batch ≤1000 с auto-split)."""
        infos = await self.products.get_info_batch(offer_ids=offer_ids)
        return [i.model_dump(mode="json") for i in infos]

    async def get_products_attributes(self, offer_ids: list[str]) -> list[dict[str, Any]]:
        """Характеристики товаров по offer_id."""
        page = await self.products.get_attributes_batch(offer_ids=offer_ids)
        return [a.model_dump(mode="json") for a in page.items]
