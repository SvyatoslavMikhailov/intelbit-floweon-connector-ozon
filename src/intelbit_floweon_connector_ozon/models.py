"""Pydantic-модели Ozon Seller API."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class FulfillmentType(StrEnum):
    fbs = "fbs"
    fbo = "fbo"
    rfbs = "rfbs"


class PostingStatus(StrEnum):
    awaiting_packaging = "awaiting_packaging"
    awaiting_deliver = "awaiting_deliver"
    delivering = "delivering"
    delivered = "delivered"
    cancelled = "cancelled"


class OzonProduct(BaseModel):
    """Товар в каталоге Ozon."""

    offer_id: str
    product_id: int = 0
    name: str
    sku: int = 0
    barcode: str = ""
    is_archived: bool = False


class OzonStock(BaseModel):
    """Остаток товара на складе Ozon."""

    offer_id: str
    warehouse_id: int
    stock: int
    reserved: int = 0


class OzonPrice(BaseModel):
    """Цена товара на Ozon."""

    offer_id: str
    price: Decimal
    old_price: Decimal = Decimal("0")
    min_price: Decimal = Decimal("0")
    currency_code: str = "RUB"


class PostingProduct(BaseModel):
    """Товарная позиция в отправлении."""

    sku: int
    name: str
    offer_id: str
    quantity: int
    price: str
    currency_code: str = "RUB"


class OzonPosting(BaseModel):
    """Отправление (заказ) Ozon FBS."""

    posting_number: str
    order_id: int
    order_number: str
    status: PostingStatus
    fulfillment_type: FulfillmentType = FulfillmentType.fbs
    created_at: str
    in_process_at: str = ""
    products: list[PostingProduct] = Field(default_factory=list)
    tracking_number: str = ""
    warehouse_id: int = 0


# --------------------------------------------------------------------------- #
# Orders — список отправлений
# --------------------------------------------------------------------------- #


class PostingsList(BaseModel):
    """Результат list_postings_fbs: страница отправлений + флаг следующей."""

    result: list[OzonPosting] = Field(default_factory=list)
    has_next: bool = False


# --------------------------------------------------------------------------- #
# Stocks — обновление остатков
# --------------------------------------------------------------------------- #


class StockUpdate(BaseModel):
    """Позиция для обновления остатка на складе FBS."""

    product_id: int
    stock: int
    warehouse_id: int
    offer_id: str = ""

    def to_ozon(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "product_id": self.product_id,
            "stock": self.stock,
            "warehouse_id": self.warehouse_id,
        }
        if self.offer_id:
            body["offer_id"] = self.offer_id
        return body


class StockUpdateItemResult(BaseModel):
    """Результат обновления одной позиции остатка."""

    product_id: int = 0
    offer_id: str = ""
    warehouse_id: int = 0
    updated: bool = False
    errors: list[dict[str, Any]] = Field(default_factory=list)


class UpdateStocksResult(BaseModel):
    """Агрегированный результат update_stocks (по всем чанкам)."""

    result: list[StockUpdateItemResult] = Field(default_factory=list)


class StockInfo(BaseModel):
    """Текущий остаток товара (get_stocks)."""

    product_id: int = 0
    offer_id: str = ""
    present: int = 0
    reserved: int = 0


# --------------------------------------------------------------------------- #
# Prices — обновление цен
# --------------------------------------------------------------------------- #


class PriceUpdate(BaseModel):
    """Позиция для обновления цены. Цены Ozon передаёт строками."""

    product_id: int
    price: str
    old_price: str = ""
    min_price: str = ""
    offer_id: str = ""
    auto_action_enabled: str = "UNKNOWN"
    currency_code: str = "RUB"

    def to_ozon(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "product_id": self.product_id,
            "price": self.price,
            "auto_action_enabled": self.auto_action_enabled,
            "currency_code": self.currency_code,
        }
        if self.old_price:
            body["old_price"] = self.old_price
        if self.min_price:
            body["min_price"] = self.min_price
        if self.offer_id:
            body["offer_id"] = self.offer_id
        return body


class PriceUpdateItemResult(BaseModel):
    """Результат обновления цены одной позиции."""

    product_id: int = 0
    offer_id: str = ""
    updated: bool = False
    errors: list[dict[str, Any]] = Field(default_factory=list)


class UpdatePricesResult(BaseModel):
    """Агрегированный результат update_prices (по всем чанкам)."""

    result: list[PriceUpdateItemResult] = Field(default_factory=list)


class PriceInfo(BaseModel):
    """Текущая цена товара (get_prices)."""

    product_id: int = 0
    offer_id: str = ""
    price: str = "0"
    old_price: str = "0"
    min_price: str = "0"
    currency_code: str = "RUB"


# --------------------------------------------------------------------------- #
# Webhooks — discriminated union по message_type
# --------------------------------------------------------------------------- #


class _WebhookBase(BaseModel):
    """Общие поля webhook-события Ozon."""

    message_id: str = ""
    seller_id: int = 0


class NewPostingEvent(_WebhookBase):
    message_type: Literal["TYPE_NEW_POSTING"]
    posting_number: str = ""
    warehouse_id: int = 0
    products: list[dict[str, Any]] = Field(default_factory=list)


class PostingCancelledEvent(_WebhookBase):
    message_type: Literal["TYPE_POSTING_CANCELLED"]
    posting_number: str = ""
    old_state: str = ""
    new_state: str = ""


class StateChangedEvent(_WebhookBase):
    message_type: Literal["TYPE_STATE_CHANGED"]
    posting_number: str = ""
    old_state: str = ""
    new_state: str = ""


class CutoffDateChangedEvent(_WebhookBase):
    message_type: Literal["TYPE_CUTOFF_DATE_CHANGED"]
    posting_number: str = ""
    new_cutoff_date: str = ""
    old_cutoff_date: str = ""


class DeliveryDateChangedEvent(_WebhookBase):
    message_type: Literal["TYPE_DELIVERY_DATE_CHANGED"]
    posting_number: str = ""
    new_delivery_date_begin: str = ""
    new_delivery_date_end: str = ""


class ChatClosedEvent(_WebhookBase):
    message_type: Literal["TYPE_CHAT_CLOSED"]
    chat_id: str = ""


class ChatMessageEvent(_WebhookBase):
    message_type: Literal["TYPE_CHAT_MESSAGE"]
    chat_id: str = ""
    message_text: str = ""


class PingEvent(BaseModel):
    message_type: Literal["TYPE_PING"]
    time: str = ""
    version: str = ""


OzonWebhookEvent = Annotated[
    NewPostingEvent
    | PostingCancelledEvent
    | StateChangedEvent
    | CutoffDateChangedEvent
    | DeliveryDateChangedEvent
    | ChatClosedEvent
    | ChatMessageEvent
    | PingEvent,
    Field(discriminator="message_type"),
]
