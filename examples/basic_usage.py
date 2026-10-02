"""Пример: чтение списка FBS-заказов из Ozon.

v0.0.1 — skeleton. Методы поднимают NotImplementedError.
Реальный пример появится в v0.1.0.
"""

import asyncio

from intelbit_floweon_connector_ozon import OzonConnector


async def main() -> None:
    connector = OzonConnector(
        config={
            "client_id": "12345",
            "api_key": "your-api-key",
            "rate_limit_rpm": 60,
            # Fail-closed: при включённом приёме вебхуков секрет обязателен.
            "webhook": {"secret": "your-webhook-secret"},
        }
    )

    # v0.0.1: вызов поднимет NotImplementedError
    # orders = await connector.list_orders(since="2026-05-01T00:00:00Z")
    print(f"OzonConnector BASE_URL: {connector.BASE_URL}")
    print("OzonConnector skeleton ready. Implementation in v0.1.0.")


if __name__ == "__main__":
    asyncio.run(main())
