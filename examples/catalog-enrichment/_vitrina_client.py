"""Тонкая обёртка над 1С-Битрикс БУС REST через входящий webhook.

ВАЖНО про БУС vs Битрикс24:
- В БУС («1С-Битрикс: Управление сайтом») НЕТ модуля `disk` и НЕТ пишущего
  `iblock.element.*` REST (только read-only get/list при включённом API_CODE).
  Запись в каталог идёт через scope `catalog`:
    * catalog.product.update      — DETAIL_TEXT + свойства (property<ID>);
    * catalog.productImage.add    — картинки base64 (DETAIL_PICTURE / MORE_PHOTO);
    * catalog.product.list        — чтение/матчинг (xmlId);
    * catalog.productProperty.list — резолв CODE свойства → ID.
- Webhook БУС читает параметры из request->get(): тело должно быть
  form-urlencoded (PHP-ключи вида fields[property26][value]), НЕ JSON.
- Для локального стенда без SSL в dbconn.php задаётся
  define('REST_APAUTH_ALLOW_HTTP', true).

Предусловия в БУС: инфоблок зарегистрирован как коммерческий каталог
(CCatalog::Add), элементы — товары (CCatalogProduct::Add).
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any

import httpx


class VitrinaApiError(RuntimeError):
    """БУС REST вернул error в теле ответа."""

    def __init__(self, error: Any, description: Any = "") -> None:
        self.error = error
        self.description = description
        super().__init__(f"Bitrix REST error {error}: {description}")


def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    """Разворачивает вложенные dict/list в плоские PHP-ключи form-urlencoded.

    {"fields": {"property26": {"value": "Белый"}}} →
        {"fields[property26][value]": "Белый"}
    {"fileContent": ["a.png", "<b64>"]} →
        {"fileContent[0]": "a.png", "fileContent[1]": "<b64>"}
    """
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}[{key}]" if prefix else str(key)
            out.update(_flatten(value, child))
    elif isinstance(obj, (list, tuple)):
        for idx, value in enumerate(obj):
            child = f"{prefix}[{idx}]" if prefix else str(idx)
            out.update(_flatten(value, child))
    else:
        if obj is None:
            out[prefix] = ""
        elif isinstance(obj, bool):
            out[prefix] = "Y" if obj else "N"
        else:
            out[prefix] = obj if isinstance(obj, str) else str(obj)
    return out


class VitrinaBusClient:
    """Клиент БУС REST через incoming webhook (без OAuth), scope `catalog`.

    base — URL вида http://host/rest/USER_ID/TOKEN (без конечного метода).
    storage_id — устаревший параметр (БУС не использует disk-модуль); игнорируется.
    _transport — для smoke-тестов через httpx.ASGITransport.
    """

    def __init__(
        self,
        webhook_url: str,
        iblock_id: int,
        storage_id: int | None = None,  # deprecated, БУС не использует disk
        timeout: float = 30.0,
        _transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = webhook_url.rstrip("/")
        self._iblock_id = iblock_id
        self._http = httpx.AsyncClient(timeout=timeout, transport=_transport)
        self._prop_ids: dict[str, int] | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, params: dict[str, Any]) -> Any:
        """POST {base}/{method}.json form-urlencoded → {result, error?}."""
        resp = await self._http.post(f"{self._base}/{method}.json", data=_flatten(params))
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise VitrinaApiError(body.get("error"), body.get("error_description"))
        return body["result"]

    # ---- чтение / матчинг --------------------------------------------------

    async def list_elements(self, start: int = 0) -> list[dict[str, Any]]:
        """catalog.product.list по IBLOCK_ID. Нормализует ключи под матчинг.

        select обязан включать iblockId, иначе БУС вернёт ошибку.
        """
        result = await self._call(
            "catalog.product.list",
            {
                "select": ["id", "iblockId", "xmlId", "code", "name"],
                "filter": {"iblockId": self._iblock_id},
                "start": start,
            },
        )
        products = result.get("products", []) if isinstance(result, dict) else (result or [])
        return [
            {
                "ID": p.get("id"),
                "XML_ID": p.get("xmlId", "") or "",
                "CODE": p.get("code", "") or "",
                "NAME": p.get("name", "") or "",
                "PROPERTY_VALUES": {},
            }
            for p in products
        ]

    async def iter_all_elements(self, page_size: int = 50) -> AsyncIterator[dict[str, Any]]:
        """Постранично прокачивает все товары (БУС использует start-offset)."""
        start = 0
        while True:
            batch = await self.list_elements(start=start)
            if not batch:
                break
            for el in batch:
                yield el
            if len(batch) < page_size:
                break
            start += len(batch)

    async def property_ids(self) -> dict[str, int]:
        """catalog.productProperty.list → {CODE: ID} для нашего инфоблока (кэш)."""
        if self._prop_ids is None:
            result = await self._call(
                "catalog.productProperty.list",
                {
                    "select": ["id", "code", "iblockId"],
                    "filter": {"iblockId": self._iblock_id},
                },
            )
            items = (
                result.get("productProperties", [])
                if isinstance(result, dict)
                else (result or [])
            )
            self._prop_ids = {
                p["code"]: int(p["id"])
                for p in items
                if p.get("code") and str(p.get("iblockId")) == str(self._iblock_id)
            }
        return self._prop_ids

    # ---- запись ------------------------------------------------------------

    async def add_image(
        self, product_id: int, file_content: bytes, file_name: str, *, primary: bool
    ) -> Any:
        """catalog.productImage.add — base64 → DETAIL_PICTURE (primary) или MORE_PHOTO.

        Картинка сразу прикрепляется к товару, disk-модуль не нужен.
        """
        b64 = base64.b64encode(file_content).decode("ascii")
        image_type = "DETAIL_PICTURE" if primary else "MORE_PHOTO"
        result = await self._call(
            "catalog.productImage.add",
            {
                "fields": {"productId": product_id, "type": image_type},
                "fileContent": [file_name, b64],
            },
        )
        return result.get("productImage", result) if isinstance(result, dict) else result

    async def update_product(
        self,
        product_id: int,
        *,
        detail_text: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> list[str]:
        """catalog.product.update — DETAIL_TEXT + строковые свойства по CODE.

        Свойства адресуются по property<ID>; CODE резолвится в ID.
        Возвращает список CODE свойств, которых нет в инфоблоке (пропущены).
        """
        fields: dict[str, Any] = {}
        if detail_text is not None:
            fields["detailText"] = detail_text
            fields["detailTextType"] = "text"

        unknown: list[str] = []
        if attributes:
            prop_ids = await self.property_ids()
            for code, value in attributes.items():
                pid = prop_ids.get(code)
                if pid is None:
                    unknown.append(code)
                    continue
                fields[f"property{pid}"] = {"value": value}

        if fields:
            await self._call("catalog.product.update", {"id": product_id, "fields": fields})
        return unknown
