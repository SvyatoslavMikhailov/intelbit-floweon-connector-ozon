# intelbit-floweon-connector-ozon

Коннектор Ozon Seller API для **Интелбит.Фловеон** — открытой интеграционной шины данных для торговых компаний.

## Что умеет (v0.0.1 — скелет)

- Typed Pydantic-модели Ozon-сущностей: Posting (FBS), Product, Stock, Price
- Skeleton `OzonConnector` по контракту ADR-006 (Plugin API)
- Заглушки Orders / Stocks / Prices / Webhooks — реализация в фазе 4 MVP

## Что будет в v0.1.0 (Q2 2027, MVP Фловеона)

- Чтение заказов FBS через `POST /v3/posting/fbs/list`
- Push остатков `POST /v1/product/info/stocks-by-warehouse/fbs`
- Push цен `POST /v1/product/import/prices`
- Webhook-receiver для push-уведомлений Ozon (новые заказы, смены статусов)
- Rate-limiting через tenacity (retry + exponential backoff)

## Целевой сценарий

Маркетплейс↔1С: заказы из Ozon синхронизируются с 1С УТ 11.5 / КА 2.5 через Фловеон.
Первый пилотный клиент — Cyberflot (Care Friend, Fidelica).

## Установка

```bash
pip install intelbit-floweon-connector-ozon
```

## Быстрый старт

```python
from intelbit_floweon_connector_ozon import OzonConnector

connector = OzonConnector(config={
    "client_id": "12345",
    "api_key": "your-api-key",
})
# v0.0.1: методы — stubs, реализация в v0.1.0
```

## Конфигурация

Параметры подключения — в [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Связанные проекты

- **Интелбит.Фловеон** — главный продукт, использующий этот коннектор
- [intelbit-floweon-monorepo](https://github.com/SvyatoslavMikhailov/intelbit-floweon-monorepo) — monorepo ядра Фловеона
- [intelbit-floweon-connector-onec](https://github.com/SvyatoslavMikhailov/intelbit-floweon-connector-onec) — коннектор 1С
