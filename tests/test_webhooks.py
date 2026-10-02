"""Тесты OzonWebhookReceiver — парсинг, валидация, дедуп."""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest

from intelbit_floweon_connector_ozon.exceptions import WebhookValidationError
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
from tests.conftest import load_mock

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
def receiver() -> OzonWebhookReceiver:
    return OzonWebhookReceiver()


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


def test_verify_ip_allowlist_blocks() -> None:
    recv = OzonWebhookReceiver({"allowed_ips": ["1.2.3.4"]})
    with pytest.raises(WebhookValidationError):
        recv.verify_request({"X-Forwarded-For": "9.9.9.9"}, b"{}")


def test_verify_ip_allowlist_allows() -> None:
    recv = OzonWebhookReceiver({"allowed_ips": ["1.2.3.4"]})
    recv.verify_request({"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}, b"{}")  # не бросает


async def test_deduplicate(receiver) -> None:
    redis = fakeredis.aioredis.FakeRedis()
    assert await receiver.deduplicate("msg-0001", redis) is False  # первый раз — не дубль
    assert await receiver.deduplicate("msg-0001", redis) is True  # повтор — дубль
    assert await receiver.deduplicate("msg-0002", redis) is False
