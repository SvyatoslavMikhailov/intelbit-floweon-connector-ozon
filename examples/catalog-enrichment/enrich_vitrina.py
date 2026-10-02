"""ETL: разовое обогащение каталога 1С-Битрикс БУС данными из Ozon Seller API.

Сопоставление по полю элемента инфоблока (XML_ID / CODE / PROPERTY_*) == Ozon offer_id.
Safety: по умолчанию --dry-run (в БУС ничего не пишется); реальная запись — только с --apply.

См. README.md.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from _vitrina_client import VitrinaBusClient

from intelbit_river_connector_ozon.connector import OzonConnector

logger = logging.getLogger("enrich_vitrina")

# Грубая транслитерация для символьных кодов свойств (БУС любит латиницу).
_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def slugify_property_code(name: str) -> str:
    """«Цвет» → COLOR-подобный код: транслит, не-alnum → _, верхний регистр."""
    slug = name.strip().lower().translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug.upper()


# --------------------------------------------------------------------------- #
# План обогащения
# --------------------------------------------------------------------------- #


@dataclass
class ImageRef:
    url: str
    name: str
    is_primary: bool


@dataclass
class EnrichmentPlan:
    new_description: str | None = None
    images_to_upload: list[ImageRef] = field(default_factory=list)
    new_attributes: list[tuple[str, str]] = field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "description": "yes" if self.new_description else "no",
            "images": len(self.images_to_upload),
            "attributes": len(self.new_attributes),
        }


@dataclass
class ApplyResult:
    description_updated: bool = False
    primary_picture_set: bool = False
    images_uploaded: list[dict[str, Any]] = field(default_factory=list)
    image_errors: list[dict[str, Any]] = field(default_factory=list)
    properties_set: int = 0

    def summary_dict(self) -> dict[str, Any]:
        return {
            "description": "yes" if self.description_updated else "no",
            "images": len(self.images_uploaded),
            "image_errors": len(self.image_errors),
            "properties_set": self.properties_set,
        }


def build_enrichment_plan(
    info: dict[str, Any], attrs: list[dict[str, Any]], args: argparse.Namespace
) -> EnrichmentPlan:
    plan = EnrichmentPlan()

    if not args.skip_description and info.get("description"):
        plan.new_description = info["description"]

    if not args.skip_images:
        images = info.get("images", [])[: args.max_images_per_product]
        for img in images:
            url = img.get("file_name", "")
            if not url:
                continue
            name = url.rsplit("/", 1)[-1] or f"{info['offer_id']}.jpg"
            plan.images_to_upload.append(
                ImageRef(url=url, name=name, is_primary=bool(img.get("default")))
            )

    if not args.skip_attributes:
        for attr in attrs:
            name = attr.get("name") or f"attr_{attr.get('id')}"
            values = [v.get("value", "") for v in attr.get("values", []) if v.get("value")]
            if values:
                plan.new_attributes.append((name, ", ".join(values)))

    return plan


def extract_match_key(element: dict[str, Any], match_field: str) -> str:
    if match_field.startswith("PROPERTY_"):
        prop = match_field[len("PROPERTY_") :]
        props = element.get("PROPERTY_VALUES", {}) or {}
        return str(props.get(prop, "") or "")
    return str(element.get(match_field, "") or "")


async def download_image(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


# --------------------------------------------------------------------------- #
# Применение к БУС
# --------------------------------------------------------------------------- #


async def apply_to_vitrina(
    vitrina: VitrinaBusClient,
    element_id: int,
    plan: EnrichmentPlan,
    args: argparse.Namespace,
) -> ApplyResult:
    result = ApplyResult()

    # Картинки: первая is_primary → DETAIL_PICTURE, остальные → MORE_PHOTO (галерея).
    # catalog.productImage.add прикрепляет файл к товару напрямую (без disk-модуля).
    primary_done = False
    for img in plan.images_to_upload:
        try:
            content = await download_image(img.url)
            primary = img.is_primary and not primary_done
            await vitrina.add_image(element_id, content, img.name, primary=primary)
            if primary:
                primary_done = True
                result.primary_picture_set = True
            result.images_uploaded.append({"name": img.name, "primary": primary})
        except Exception as exc:
            result.image_errors.append({"name": img.name, "error": str(exc)})

    # DETAIL_TEXT + характеристики OZON_* одним catalog.product.update.
    detail_text = plan.new_description
    attributes: dict[str, str] = {
        f"{args.attribute_prefix}{slugify_property_code(name)}": value
        for name, value in plan.new_attributes
    }
    unknown = await vitrina.update_product(
        element_id, detail_text=detail_text, attributes=attributes
    )
    if unknown:
        logger.warning(
            "element_id=%s: нет свойств в инфоблоке, пропущены: %s",
            element_id,
            ", ".join(unknown),
        )
    result.description_updated = detail_text is not None
    result.properties_set = len(attributes) - len(unknown)

    return result


# --------------------------------------------------------------------------- #
# Основной прогон
# --------------------------------------------------------------------------- #

_MATCHED_FIELDS = ["offer_id", "element_id", "description", "images", "attributes"]
_APPLY_FIELDS = [
    "offer_id",
    "element_id",
    "description",
    "images",
    "image_errors",
    "properties_set",
]


async def run_enrichment(
    ozon: OzonConnector,
    vitrina: VitrinaBusClient,
    args: argparse.Namespace,
    out_dir: Path,
) -> dict[str, int]:
    """Ядро ETL. Возвращает счётчики {matched, skipped, errors}."""
    logger.info("Индексируем элементы инфоблока %s…", args.vitrina_iblock_id)
    vitrina_index: dict[str, int] = {}
    async for el in vitrina.iter_all_elements():
        key = extract_match_key(el, args.match_field)
        if key:
            vitrina_index[key] = int(el["ID"])
    logger.info("Проиндексировано %d элементов БУС", len(vitrina_index))

    counts = {"matched": 0, "skipped": 0, "errors": 0}

    with (
        (out_dir / "matched.csv").open("w", newline="", encoding="utf-8") as fm,
        (out_dir / "skipped.csv").open("w", newline="", encoding="utf-8") as fs,
        (out_dir / "errors.csv").open("w", newline="", encoding="utf-8") as fe,
    ):
        fields = _MATCHED_FIELDS if args.dry_run else _APPLY_FIELDS
        matched_writer = csv.DictWriter(fm, fieldnames=fields)
        skipped_writer = csv.DictWriter(fs, fieldnames=["offer_id", "reason"])
        errors_writer = csv.DictWriter(fe, fieldnames=["offer_id", "error", "type"])
        matched_writer.writeheader()
        skipped_writer.writeheader()
        errors_writer.writeheader()

        last_id, processed = "", 0
        while True:
            page = await ozon.list_products(last_id=last_id, limit=1000)
            items = page["items"]
            if args.limit:
                items = items[: max(0, args.limit - processed)]
            if not items:
                break

            offer_ids = [it["offer_id"] for it in items]
            infos = await ozon.get_products_info(offer_ids)
            attrs_pages = await ozon.get_products_attributes(offer_ids)
            attrs_by_offer = {a["offer_id"]: a["attributes"] for a in attrs_pages}

            for info in infos:
                offer_id = info["offer_id"]
                element_id = vitrina_index.get(offer_id)
                if not element_id:
                    skipped_writer.writerow(
                        {"offer_id": offer_id, "reason": "not_found_in_vitrina"}
                    )
                    counts["skipped"] += 1
                    continue
                try:
                    plan = build_enrichment_plan(info, attrs_by_offer.get(offer_id, []), args)
                    if args.dry_run:
                        matched_writer.writerow(
                            {"offer_id": offer_id, "element_id": element_id, **plan.summary_dict()}
                        )
                    else:
                        res = await apply_to_vitrina(vitrina, element_id, plan, args)
                        matched_writer.writerow(
                            {"offer_id": offer_id, "element_id": element_id, **res.summary_dict()}
                        )
                    counts["matched"] += 1
                except Exception as exc:
                    errors_writer.writerow(
                        {"offer_id": offer_id, "error": str(exc), "type": type(exc).__name__}
                    )
                    counts["errors"] += 1
                    logger.exception("Ошибка для offer_id=%s", offer_id)

            processed += len(items)
            if args.limit and processed >= args.limit:
                break
            last_id = page["last_id"]
            if not last_id:
                break

    logger.info(
        "Готово: matched=%d skipped=%d errors=%d → %s",
        counts["matched"],
        counts["skipped"],
        counts["errors"],
        out_dir,
    )
    return counts


def build_ozon_connector(args: argparse.Namespace) -> OzonConnector:
    return OzonConnector(
        {
            "client_id": args.ozon_client_id,
            "api_key": args.ozon_api_key,
            "base_url": args.ozon_base_url,
        }
    )


async def main(args: argparse.Namespace) -> dict[str, int]:
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    prefix = "dry-" if args.dry_run else ""
    out_dir = Path(args.out_dir) if args.out_dir else Path("out") / f"{prefix}run-{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(message)s")

    ozon = build_ozon_connector(args)
    vitrina = VitrinaBusClient(
        args.vitrina_webhook_url, args.vitrina_iblock_id, args.vitrina_storage_id
    )
    try:
        return await run_enrichment(ozon, vitrina, args, out_dir)
    finally:
        await vitrina.aclose()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Обогащение каталога БУС данными из Ozon.")
    p.add_argument("--ozon-client-id", default=os.environ.get("OZON_CLIENT_ID", ""))
    p.add_argument("--ozon-api-key", default=os.environ.get("OZON_API_KEY", ""))
    p.add_argument(
        "--ozon-base-url", default=os.environ.get("OZON_BASE_URL", OzonConnector.BASE_URL)
    )
    p.add_argument("--vitrina-webhook-url", default=os.environ.get("VITRINA_WEBHOOK_URL", ""))
    p.add_argument(
        "--vitrina-iblock-id", type=int, default=int(os.environ.get("VITRINA_IBLOCK_ID", "0"))
    )
    p.add_argument(
        "--vitrina-storage-id", type=int, default=int(os.environ.get("VITRINA_STORAGE_ID", "0"))
    )
    p.add_argument("--match-field", default="XML_ID")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    p.add_argument("--apply", dest="dry_run", action="store_false")
    p.add_argument("--skip-images", action="store_true")
    p.add_argument("--skip-attributes", action="store_true")
    p.add_argument("--skip-description", action="store_true")
    p.add_argument("--max-images-per-product", type=int, default=5)
    p.add_argument("--gallery-property", default="MORE_PHOTO")
    p.add_argument("--attribute-prefix", default="OZON_")
    p.add_argument("--out-dir", default="")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


if __name__ == "__main__":
    parsed = build_parser().parse_args()
    asyncio.run(main(parsed))
