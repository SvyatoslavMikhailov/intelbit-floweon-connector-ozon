"""OzonWebhookReceiver — приём push-уведомлений Ozon (8 типов + PING)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter, ValidationError

from intelbit_floweon_connector_ozon.exceptions import WebhookValidationError
from intelbit_floweon_connector_ozon.models import OzonWebhookEvent, PingEvent

# Типы событий Ozon (MVP по докам).
TYPE_NEW_POSTING = "TYPE_NEW_POSTING"
TYPE_POSTING_CANCELLED = "TYPE_POSTING_CANCELLED"
TYPE_STATE_CHANGED = "TYPE_STATE_CHANGED"
TYPE_CUTOFF_DATE_CHANGED = "TYPE_CUTOFF_DATE_CHANGED"
TYPE_DELIVERY_DATE_CHANGED = "TYPE_DELIVERY_DATE_CHANGED"
TYPE_CHAT_CLOSED = "TYPE_CHAT_CLOSED"
TYPE_CHAT_MESSAGE = "TYPE_CHAT_MESSAGE"
TYPE_PING = "TYPE_PING"

_event_adapter: TypeAdapter[Any] = TypeAdapter(OzonWebhookEvent)
_DEDUP_TTL_SEC = 24 * 60 * 60


class OzonWebhookReceiver:
    """Валидация, парсинг и дедупликация webhook-ов Ozon.

    Ozon не подписывает запросы HMAC: проверяется IP-allowlist (если задан) и
    secret в теле запроса.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self._secret: str = config.get("secret", "")
        self._allowed_ips: set[str] = set(config.get("allowed_ips", []))

    def verify_request(self, headers: dict[str, str], body: bytes) -> None:
        """Проверить источник и secret. Бросает WebhookValidationError при несоответствии."""
        if self._allowed_ips:
            client_ip = _client_ip(headers)
            if client_ip not in self._allowed_ips:
                raise WebhookValidationError(f"IP {client_ip!r} не в allowlist")

        if self._secret:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise WebhookValidationError(f"Тело webhook не JSON: {exc}") from exc
            if parsed.get("secret_key") != self._secret:
                raise WebhookValidationError("Неверный secret_key в теле webhook")

    def parse_event(self, body: bytes) -> Any:
        """JSON-тело → Pydantic-событие (discriminated union по message_type)."""
        try:
            return _event_adapter.validate_json(body)
        except ValidationError as exc:
            raise WebhookValidationError(f"Неизвестный или некорректный webhook: {exc}") from exc

    def respond_ping(self, event: Any) -> dict[str, Any]:
        """Ответ на PING — подтверждение доступности endpoint."""
        if isinstance(event, PingEvent):
            return {"result": True}
        raise WebhookValidationError("respond_ping вызван не для PING-события")

    async def deduplicate(self, message_id: str, redis_client: Any) -> bool:
        """Зарегистрировать message_id в Redis (TTL 24h). True — дубль (уже видели)."""
        key = f"ozon:webhook:{message_id}"
        was_set = await redis_client.set(key, "1", nx=True, ex=_DEDUP_TTL_SEC)
        return not was_set


def _client_ip(headers: dict[str, str]) -> str:
    lowered = {k.lower(): v for k, v in headers.items()}
    forwarded = lowered.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return lowered.get("x-real-ip", "")
