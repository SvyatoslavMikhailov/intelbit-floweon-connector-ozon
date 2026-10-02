"""OzonWebhookReceiver — приём push-уведомлений Ozon (8 типов + PING)."""

from __future__ import annotations

import hmac
import ipaddress
import json
from collections.abc import Iterable
from typing import Any

from pydantic import TypeAdapter, ValidationError

from intelbit_floweon_connector_ozon.exceptions import (
    ConfigurationError,
    WebhookValidationError,
)
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


IpNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class OzonWebhookReceiver:
    """Валидация, парсинг и дедупликация webhook-ов Ozon.

    Ozon не подписывает запросы HMAC: проверяется IP-allowlist (если задан) и
    secret в теле запроса. Fail-closed: при включённом приёме вебхуков пустой
    secret — ошибка конфигурации на инициализации, а не «принимать всё».

    Конфиг (секция ``webhook``):
        enabled: приём вебхуков включён (default true).
        secret: ожидаемый ``secret_key`` в теле (обязателен при enabled).
        allowed_ips: IP/CIDR-allowlist источника (обязателен, если задан trusted_proxies).
        trusted_proxies: IP/CIDR reverse-proxy, которым разрешено сообщать
            реальный адрес клиента через ``X-Forwarded-For``.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self._enabled: bool = bool(config.get("enabled", True))
        self._secret: str = str(config.get("secret") or "")
        self._allowed: list[IpNetwork] = _parse_networks(config.get("allowed_ips"), "allowed_ips")
        self._trusted_proxies: list[IpNetwork] = _parse_networks(
            config.get("trusted_proxies"), "trusted_proxies"
        )
        if not self._enabled:
            return
        if not self._secret:
            raise ConfigurationError(
                "webhook.secret не задан: при включённом приёме вебхуков (webhook.enabled) "
                "секрет обязателен"
            )
        if self._trusted_proxies and not self._allowed:
            raise ConfigurationError(
                "webhook.trusted_proxies задан без webhook.allowed_ips: доверие "
                "X-Forwarded-For без allowlist не имеет смысла"
            )

    @property
    def enabled(self) -> bool:
        """Включён ли приём вебхуков."""
        return self._enabled

    def verify_request(
        self, headers: dict[str, str], body: bytes, peer_ip: str | None = None
    ) -> None:
        """Проверить источник и secret. Бросает WebhookValidationError при несоответствии.

        Args:
            headers: HTTP-заголовки запроса.
            body: сырое тело запроса.
            peer_ip: адрес непосредственного TCP-собеседника (peer сокета).
                ``X-Forwarded-For`` учитывается только если peer входит в
                ``trusted_proxies``; иначе клиентом считается сам peer.
        """
        if not self._enabled:
            raise WebhookValidationError("Приём вебхуков выключен (webhook.enabled=false)")

        if self._allowed:
            client_ip = _client_ip(headers, peer_ip, self._trusted_proxies)
            if client_ip is None or not _in_networks(client_ip, self._allowed):
                raise WebhookValidationError(f"IP {client_ip!r} не в allowlist")

        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise WebhookValidationError(f"Тело webhook не JSON: {exc}") from exc
        received = parsed.get("secret_key") if isinstance(parsed, dict) else None
        if not isinstance(received, str) or not hmac.compare_digest(
            received.encode("utf-8"), self._secret.encode("utf-8")
        ):
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


def _parse_networks(raw: Any, key: str) -> list[IpNetwork]:
    """Список IP/CIDR из конфига → сети. Невалидная запись — ConfigurationError (без значения)."""
    if not raw:
        return []
    if isinstance(raw, str) or not isinstance(raw, Iterable):
        raise ConfigurationError(f"webhook.{key} должен быть списком IP/CIDR")
    result: list[IpNetwork] = []
    for index, item in enumerate(raw):
        try:
            result.append(ipaddress.ip_network(str(item).strip(), strict=False))
        except ValueError as exc:
            raise ConfigurationError(f"webhook.{key}[{index}]: некорректный IP/CIDR") from exc
    return result


def _parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _in_networks(ip: str, networks: list[IpNetwork]) -> bool:
    addr = _parse_ip(ip)
    return addr is not None and any(addr in net for net in networks)


def _client_ip(
    headers: dict[str, str], peer_ip: str | None, trusted_proxies: list[IpNetwork]
) -> str | None:
    """Определить IP клиента.

    ``X-Forwarded-For`` подделывается кем угодно, поэтому читается только когда
    непосредственный peer — доверенный прокси. Цепочка разбирается справа налево:
    первый адрес, не входящий в ``trusted_proxies``, и есть клиент.
    Без доверенного peer клиентом считается сам peer.
    """
    if peer_ip is None or not _in_networks(peer_ip, trusted_proxies):
        return peer_ip
    lowered = {k.lower(): v for k, v in headers.items()}
    forwarded = [part.strip() for part in lowered.get("x-forwarded-for", "").split(",")]
    for hop in reversed([part for part in forwarded if part]):
        if not _in_networks(hop, trusted_proxies):
            return hop
    return peer_ip
