# Конфигурация коннектора Ozon

## Параметры

| Параметр | Тип | Обязательный | Описание |
|---|---|---|---|
| `client_id` | string | да | Client-Id из кабинета Ozon Seller |
| `api_key` | string | да | Api-Key из кабинета Ozon Seller |
| `rate_limit_rpm` | int | нет | Лимит запросов/мин, default 60 |
| `webhook.enabled` | bool | нет | Приём вебхуков, default `true` |
| `webhook.secret` | string | да, если `webhook.enabled` | Ожидаемый `secret_key` в теле push-уведомления; без него — `ConfigurationError` |
| `webhook.allowed_ips` | list[str] | нет | IP/CIDR-allowlist источника |
| `webhook.trusted_proxies` | list[str] | нет | IP/CIDR прокси, чей `X-Forwarded-For` учитывается; требует `allowed_ips` |
| `timeout` | int | нет | Таймаут HTTP (сек), default 30 |

## Где взять Client-Id и Api-Key

1. Личный кабинет Ozon Seller → Настройки → API-ключи
2. Создать ключ с правами: Заказы (чтение/запись), Товары (чтение/запись)

## Пример конфига в preset.yaml

```yaml
connectors:
  ozon:
    plugin: intelbit-floweon-connector-ozon
    version: ">=0.1.0"
    config:
      client_id: "${secrets.OZON_CLIENT_ID}"
      api_key: "${secrets.OZON_API_KEY}"
      rate_limit_rpm: 60
      webhook:
        secret: "${secrets.OZON_WEBHOOK_SECRET}"
```
