"""Модели Ozon Product API (list / info / attributes) — для ETL-обогащения.

Детальная карточка названа OzonProductInfo, чтобы не конфликтовать с уже
существующей моделью OzonProduct (каталожный stub в models.py).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProductListItem(BaseModel):
    product_id: int
    offer_id: str
    has_fbo_stocks: bool | None = None
    has_fbs_stocks: bool | None = None
    archived: bool | None = None


class ProductListPage(BaseModel):
    items: list[ProductListItem] = Field(default_factory=list)
    total: int = 0
    last_id: str = ""


class OzonImage(BaseModel):
    file_name: str  # полный URL на Ozon CDN
    default: bool = False
    index: int = 0


class OzonProductInfo(BaseModel):
    product_id: int
    offer_id: str
    name: str = ""
    description: str | None = None
    barcode: str | None = None
    barcodes: list[str] = Field(default_factory=list)
    primary_image: str | None = None
    images: list[OzonImage] = Field(default_factory=list)
    weight: int | None = None  # граммы
    depth: int | None = None  # миллиметры
    width: int | None = None
    height: int | None = None


class OzonAttributeValue(BaseModel):
    dictionary_value_id: int | None = None
    value: str = ""


class OzonProductAttribute(BaseModel):
    id: int
    name: str = ""  # человекочитаемое имя (может прийти пустым)
    values: list[OzonAttributeValue] = Field(default_factory=list)


class OzonProductAttributes(BaseModel):
    id: int  # product_id
    offer_id: str = ""
    attributes: list[OzonProductAttribute] = Field(default_factory=list)


class AttributesPage(BaseModel):
    items: list[OzonProductAttributes] = Field(default_factory=list)
    last_id: str = ""
