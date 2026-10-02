# Архитектура коннектора Ozon

## Опорные документы

- **ADR-006** — Plugin API contract и SDK. Определяет базовый lifecycle и Connector ABC.
- **D-5 §1.3** — Объём MVP: Ozon Seller API (заказы read, остатки push, цены push, статусы).
- **D-6** — Пилотный клиент Cyberflot (Care Friend, Fidelica), Ход 2, Q1-Q2 2027.

## Модули

| Модуль | Назначение | Статус |
|---|---|---|
| `connector.py` | Фасад OzonConnector (ADR-006) | Stub (фаза 4) |
| `auth.py` | Client-Id + Api-Key headers | Реализован |
| `orders.py` | Заказы FBS/FBO | Stub (фаза 4) |
| `stocks.py` | Остатки на складах | Stub (фаза 4) |
| `prices.py` | Цены товаров | Stub (фаза 4) |
| `webhooks.py` | Push-уведомления Ozon | Stub (фаза 4) |
| `rate_limiter.py` | Rate limiting (tenacity) | Placeholder |

## Целевой сценарий MVP: Ozon FBS ↔ 1С УТ 11.5

```
Ozon → webhook (новый заказ) → Фловеон (workflow-engine) → 1С (OneCConnector) → резерв склада
1С → остатки изменились → Фловеон → Ozon (OzonConnector.update_stocks)
1С → цены изменились → Фловеон → Ozon (OzonConnector.update_prices)
```

## Rate Limits Ozon API

- Большинство методов: ~1 req/s
- Импорт цен/остатков: пакетные (до 1000 позиций за вызов)
- Детали: [docs/OZON_API_QUIRKS.md](OZON_API_QUIRKS.md)

## Подключение floweon-sdk

Этот коннектор пока не зависит от `floweon-sdk`. При будущей привязке использовать **публичный git-тег** `intelbit-floweon-sdk @ vX.Y.Z` (репозиторий `SvyatoslavMikhailov/intelbit-floweon-sdk`), **не** path в приватный `intelbit-floweon-monorepo`.
