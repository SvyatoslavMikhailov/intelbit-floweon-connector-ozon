# catalog-enrichment

Generic CLI-инструмент для разового обогащения каталога 1С-Битрикс БУС
(описание + характеристики + фотографии) данными из Ozon Seller API.

Сопоставление — по полю элемента инфоблока (XML_ID / CODE / PROPERTY_*) == Ozon `offer_id`.
Базовые поля (артикул, наименование, цена, остаток) уже синхронизируются из 1С
через preset `onec-vitrina-pilot` — этот скрипт добавляет **только то, чего нет**.

## Предусловия

- В БУС создан инфоблок каталога (тип `catalog` или совместимый).
- Элементы инфоблока имеют поле, совпадающее с `offer_id` Ozon (для Cyberflot: `XML_ID` = Артикул).
- Создано **множественное свойство** типа `file` с кодом `MORE_PHOTO` (типовое для `bitrix:catalog` галереи).
- Свойства характеристик (`OZON_COLOR`, `OZON_BREND`, …) **созданы заранее** в инфоблоке — скрипт их НЕ создаёт.
- На портале БУС создан **входящий webhook** с правами `iblock` + `disk`.
- Известен `STORAGE_ID` Disk-модуля (`disk.storage.getlist`).

## Использование

1. `cp .env.example .env` и заполнить ключи Ozon + webhook БУС + IBLOCK_ID + STORAGE_ID.
2. Сухой прогон на 20 товарах (по умолчанию `--dry-run`, в БУС ничего не пишется):

       uv run python enrich_vitrina.py --limit 20

3. Проверить `out/dry-run-YYYYMMDD-HHMMSS/matched.csv` — что планируется.
4. Реальный прогон:

       uv run python enrich_vitrina.py --limit 20 --apply

5. Постепенно увеличивать: `--limit 50 → 500 → весь каталог`.

`uv run python enrich_vitrina.py --help` — все опции.

## ⚠️ Взаимодействие с preset `onec-vitrina-pilot`

Workflow `catalog-publish` пресета синхронизирует базовые поля из 1С в БУС.
Если он трогает `DETAIL_TEXT` / `DETAIL_PICTURE` / `MORE_PHOTO` / `OZON_*` — наше
обогащение затрётся на следующей синхронизации. Перед первым `--apply` проверь
mapping `packages/presets/onec-vitrina-pilot/mappings/product-to-listing.yaml`
в `intelbit-floweon-monorepo`:

1. Убрать эти поля из mapping (рекомендуется, если 1С их не наполняет), **или**
2. Временно отключить workflow `catalog-publish` на время пилотного показа, **или**
3. Перевести его в режим «вставлять только при создании», без апдейта.
