"""Тесты OzonWebhookReceiver — парсинг, валидация, дедуп."""

from __future__ import annotations

import json
from typing import Any

import fakeredis.aioredis
import pytest

from intelbit_floweon_connector_ozon.exceptions import ConfigurationError, WebhookValidationError
from intelbit_floweon_connector_ozon.models import (
    ChatClosedEvent,
    ChatMessageEvent,
    CutoffDateChangedEvent,
    DeliveryDateChangedEvent,
    NewPostingEvent,
    PingEvent,
    PostingCancelledEvent,
    StateChangedEvent,
)
from intelbit_floweon_connector_ozon.webhooks import OzonWebhookReceiver
from tests.conftest import TEST_WEBHOOK_SECRET, load_mock, signed_body

ALL_TYPES = [
    ("TYPE_NEW_POSTING", NewPostingEvent),
    ("TYPE_POSTING_CANCELLED", PostingCancelledEvent),
    ("TYPE_STATE_CHANGED", StateChangedEvent),
    ("TYPE_CUTOFF_DATE_CHANGED", CutoffDateChangedEvent),
    ("TYPE_DELIVERY_DATE_CHANGED", DeliveryDateChangedEvent),
    ("TYPE_CHAT_CLOSED", ChatClosedEvent),
    ("TYPE_CHAT_MESSAGE", ChatMessageEvent),
    ("TYPE_PING", PingEvent),
]


@pytest.fixture
def receiver(webhook_config: dict[str, Any]) -> OzonWebhookReceiver:
    return OzonWebhookReceiver(webhook_config)


@pytest.mark.parametrize(("message_type", "expected_cls"), ALL_TYPES)
def test_parse_all_8_event_types(receiver, message_type, expected_cls) -> None:
    body = json.dumps({"message_type": message_type, "message_id": "m1"}).encode()
    event = receiver.parse_event(body)
    assert isinstance(event, expected_cls)


def test_parse_new_posting_fields(receiver) -> None:
    body = json.dumps(load_mock("webhooks/new_posting.json")).encode()
    event = receiver.parse_event(body)
    assert isinstance(event, NewPostingEvent)
    assert event.posting_number == "12345678-0001-1"
    assert event.products[0]["sku"] == 123456


def test_parse_unknown_type_raises(receiver) -> None:
    body = json.dumps({"message_type": "TYPE_UNKNOWN_X"}).encode()
    with pytest.raises(WebhookValidationError):
        receiver.parse_event(body)


def test_ping_respond(receiver) -> None:
    event = receiver.parse_event(json.dumps(load_mock("webhooks/ping.json")).encode())
    assert receiver.respond_ping(event) == {"result": True}


def test_respond_ping_rejects_non_ping(receiver) -> None:
    event = receiver.parse_event(json.dumps(load_mock("webhooks/state_changed.json")).encode())
    with pytest.raises(WebhookValidationError):
        receiver.respond_ping(event)


def test_verify_valid_secret() -> None:
    recv = OzonWebhookReceiver({"secret": "s3cr3t"})
    body = json.dumps({"message_type": "TYPE_PING", "secret_key": "s3cr3t"}).encode()
    recv.verify_request({}, body)  # не бросает


def test_verify_invalid_secret() -> None:
    recv = OzonWebhookReceiver({"secret": "s3cr3t"})
    body = json.dumps({"message_type": "TYPE_PING", "secret_key": "wrong"}).encode()
    with pytest.raises(WebhookValidationError):
        recv.verify_request({}, body)


def test_verify_missing_secret_key_in_body() -> None:
    recv = OzonWebhookReceiver({"secret": "s3cr3t"})
    with pytest.raises(WebhookValidationError):
        recv.verify_request({}, b'{"message_type": "TYPE_PING"}')


# --------------------------------------------------------------------------- #
# Fail-closed конфигурации
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", [None, {}, {"secret": ""}, {"secret": None}])
def test_missing_secret_raises_configuration_error(config: dict[str, Any] | None) -> None:
    with pytest.raises(ConfigurationError, match=r"webhook\.secret"):
        OzonWebhookReceiver(config)


def test_configuration_error_is_value_error() -> None:
    assert issubclass(ConfigurationError, ValueError)


def test_disabled_webhooks_do_not_require_secret_but_reject_requests() -> None:
    recv = OzonWebhookReceiver({"enabled": False})
    assert recv.enabled is False
    with pytest.raises(WebhookValidationError):
        recv.verify_request({}, signed_body({"message_type": "TYPE_PING"}))


def test_trusted_proxies_without_allowed_ips_raises() -> None:
    with pytest.raises(ConfigurationError, match="allowed_ips"):
        OzonWebhookReceiver({"secret": "s3cr3t", "trusted_proxies": ["10.0.0.1"]})


def test_invalid_cidr_raises_without_value() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        OzonWebhookReceiver({"secret": "s3cr3t", "allowed_ips": ["not-an-ip-SENTINEL"]})
    assert "SENTINEL" not in str(exc_info.value)


def test_secret_never_in_exception_text() -> None:
    recv = OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET})
    body = json.dumps({"message_type": "TYPE_PING", "secret_key": "wrong"}).encode()
    with pytest.raises(WebhookValidationError) as exc_info:
        recv.verify_request({}, body)
    assert TEST_WEBHOOK_SECRET not in str(exc_info.value)
    with pytest.raises(ConfigurationError) as cfg_exc:
        OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET, "trusted_proxies": ["10.0.0.1"]})
    assert TEST_WEBHOOK_SECRET not in str(cfg_exc.value)


# --------------------------------------------------------------------------- #
# IP-allowlist, peer и X-Forwarded-For
# --------------------------------------------------------------------------- #

_PING = {"message_type": "TYPE_PING"}


def test_verify_ip_allowlist_blocks_peer() -> None:
    recv = OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET, "allowed_ips": ["1.2.3.4"]})
    with pytest.raises(WebhookValidationError):
        recv.verify_request({}, signed_body(_PING), peer_ip="9.9.9.9")


def test_verify_ip_allowlist_allows_peer() -> None:
    recv = OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET, "allowed_ips": ["1.2.3.4"]})
    recv.verify_request({}, signed_body(_PING), peer_ip="1.2.3.4")  # не бросает


def test_verify_ip_allowlist_cidr() -> None:
    recv = OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET, "allowed_ips": ["1.2.3.0/24"]})
    recv.verify_request({}, signed_body(_PING), peer_ip="1.2.3.77")  # не бросает


def test_verify_allowlist_without_peer_rejects() -> None:
    """Без peer_ip источник неизвестен — fail-closed."""
    recv = OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET, "allowed_ips": ["1.2.3.4"]})
    with pytest.raises(WebhookValidationError):
        recv.verify_request({"X-Forwarded-For": "1.2.3.4"}, signed_body(_PING))


def test_xff_ignored_without_trusted_peer() -> None:
    """Подделанный X-Forwarded-For от недоверенного peer не даёт пройти allowlist."""
    recv = OzonWebhookReceiver({"secret": TEST_WEBHOOK_SECRET, "allowed_ips": ["1.2.3.4"]})
    with pytest.raises(WebhookValidationError):
        recv.verify_request({"X-Forwarded-For": "1.2.3.4"}, signed_body(_PING), peer_ip="9.9.9.9")


def test_xff_ignored_when_peer_not_in_trusted_proxies() -> None:
    recv = OzonWebhookReceiver(
        {
            "secret": TEST_WEBHOOK_SECRET,
            "allowed_ips": ["1.2.3.4"],
            "trusted_proxies": ["10.0.0.1"],
        }
    )
    with pytest.raises(WebhookValidationError):
        recv.verify_request({"X-Forwarded-For": "1.2.3.4"}, signed_body(_PING), peer_ip="9.9.9.9")


def test_xff_used_with_trusted_peer() -> None:
    recv = OzonWebhookReceiver(
        {
            "secret": TEST_WEBHOOK_SECRET,
            "allowed_ips": ["1.2.3.4"],
            "trusted_proxies": ["10.0.0.0/8"],
        }
    )
    recv.verify_request(
        {"X-Forwarded-For": "1.2.3.4"}, signed_body(_PING), peer_ip="10.0.0.1"
    )  # не бросает


def test_xff_rightmost_untrusted_hop_is_client() -> None:
    """Левые записи XFF подставляет клиент — берётся правый недоверенный hop."""
    recv = OzonWebhookReceiver(
        {
            "secret": TEST_WEBHOOK_SECRET,
            "allowed_ips": ["1.2.3.4"],
            "trusted_proxies": ["10.0.0.0/8"],
        }
    )
    with pytest.raises(WebhookValidationError):
        recv.verify_request(
            {"X-Forwarded-For": "1.2.3.4, 9.9.9.9, 10.0.0.2"},
            signed_body(_PING),
            peer_ip="10.0.0.1",
        )
    recv.verify_request(
        {"X-Forwarded-For": "5.5.5.5, 1.2.3.4, 10.0.0.2"},
        signed_body(_PING),
        peer_ip="10.0.0.1",
    )  # не бросает


async def test_deduplicate(receiver) -> None:
    redis = fakeredis.aioredis.FakeRedis()
    assert await receiver.deduplicate("msg-0001", redis) is False  # первый раз — не дубль
    assert await receiver.deduplicate("msg-0001", redis) is True  # повтор — дубль
    assert await receiver.deduplicate("msg-0002", redis) is False
