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
    "webhook": {"secret": "your-webhook-secret"},  # обязателен, см. ниже
})
# v0.0.1: методы — stubs, реализация в v0.1.0
```

## Приём вебхуков: fail-closed

Секция `webhook` конфига управляет приёмом push-уведомлений Ozon:

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `enabled` | `true` | Приём вебхуков включён |
| `secret` | — | Ожидаемый `secret_key` в теле запроса. **Обязателен** при `enabled: true` |
| `allowed_ips` | `[]` | IP/CIDR-allowlist источника. Пусто — проверка IP выключена |
| `trusted_proxies` | `[]` | IP/CIDR reverse-proxy, которым разрешено сообщать адрес клиента |

- Без `secret` при включённом приёме коннектор **не стартует**: `ConfigurationError` на
  инициализации (раньше пустой секрет означал «принимать всё»). Если коннектор используется
  только для чтения/записи API (ETL), задайте `webhook: {enabled: false}` — тогда
  `on_webhook` отклоняет любые запросы.
- Тексты ошибок содержат только имена ключей, значения секретов не логируются.

### `X-Forwarded-For` и `trusted_proxies`

Заголовок `X-Forwarded-For` подделывается любым клиентом, поэтому по умолчанию **не читается**:
источником считается непосредственный TCP-собеседник — `peer_ip`, который HTTP-сервер передаёт
в `on_webhook(headers, body, peer_ip=request.client.host)`.

- `X-Forwarded-For` учитывается, только если `peer_ip` входит в `trusted_proxies`. Цепочка
  разбирается справа налево: клиент — первый адрес, не входящий в `trusted_proxies`
  (левые записи подставляет сам клиент и доверия не заслуживают).
- `trusted_proxies` без `allowed_ips` — `ConfigurationError`: доверять прокси имеет смысл
  только ради проверки IP.
- При заданном `allowed_ips` и неизвестном `peer_ip` (не передан) запрос отклоняется.

```yaml
webhook:
  secret: "${OZON_WEBHOOK_SECRET}"
  allowed_ips: ["203.0.113.0/24"]      # пример; реальные подсети Ozon уточнить в документации
  trusted_proxies: ["10.0.0.5"]        # nginx перед Фловеоном
```

## Конфигурация

Параметры подключения — в [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Связанные проекты

- **Интелбит.Фловеон** — главный продукт, использующий этот коннектор
- [intelbit-floweon-monorepo](https://github.com/SvyatoslavMikhailov/intelbit-floweon-monorepo) — monorepo ядра Фловеона
- [intelbit-floweon-connector-onec](https://github.com/SvyatoslavMikhailov/intelbit-floweon-connector-onec) — коннектор 1С
