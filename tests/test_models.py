"""Тесты Pydantic-моделей Ozon."""

from decimal import Decimal

from intelbit_floweon_connector_ozon.models import (
    FulfillmentType,
    OzonPosting,
    OzonPrice,
    OzonProduct,
    OzonStock,
    PostingProduct,
    PostingStatus,
)


class TestOzonProduct:
    def test_defaults(self) -> None:
        p = OzonProduct(offer_id="SKU-001", name="Умная колонка")
        assert p.product_id == 0
        assert not p.is_archived
        assert p.barcode == ""

    def test_with_sku(self) -> None:
        p = OzonProduct(offer_id="SKU-002", name="Наушники", sku=123456789)
        assert p.sku == 123456789


class TestOzonStock:
    def test_basic(self) -> None:
        s = OzonStock(offer_id="SKU-001", warehouse_id=22222, stock=100)
        assert s.stock == 100
        assert s.reserved == 0

    def test_with_reserved(self) -> None:
        s = OzonStock(offer_id="SKU-001", warehouse_id=22222, stock=50, reserved=10)
        assert s.reserved == 10


class TestOzonPrice:
    def test_defaults(self) -> None:
        p = OzonPrice(offer_id="SKU-001", price=Decimal("999.00"))
        assert p.currency_code == "RUB"
        assert p.old_price == Decimal("0")
        assert p.min_price == Decimal("0")

    def test_with_old_price(self) -> None:
        p = OzonPrice(
            offer_id="SKU-001",
            price=Decimal("799.00"),
            old_price=Decimal("999.00"),
        )
        assert p.old_price > p.price


class TestOzonPosting:
    def test_defaults(self) -> None:
        posting = OzonPosting(
            posting_number="12345678-0001-1",
            order_id=111,
            order_number="12345678-0001",
            status=PostingStatus.awaiting_packaging,
            created_at="2026-05-28T10:00:00Z",
        )
        assert posting.fulfillment_type == FulfillmentType.fbs
        assert posting.products == []
        assert posting.tracking_number == ""

    def test_with_products(self) -> None:
        line = PostingProduct(
            sku=123456,
            name="Умная колонка",
            offer_id="SKU-001",
            quantity=2,
            price="999.00",
        )
        posting = OzonPosting(
            posting_number="12345678-0002-1",
            order_id=222,
            order_number="12345678-0002",
            status=PostingStatus.awaiting_deliver,
            created_at="2026-05-28T11:00:00Z",
            products=[line],
        )
        assert len(posting.products) == 1
        assert posting.products[0].quantity == 2

    def test_cancelled_status(self) -> None:
        posting = OzonPosting(
            posting_number="12345678-0003-1",
            order_id=333,
            order_number="12345678-0003",
            status=PostingStatus.cancelled,
            created_at="2026-05-28T12:00:00Z",
        )
        assert posting.status == PostingStatus.cancelled
