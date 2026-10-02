"""Базовый HTTP-клиент Ozon: единый POST с rate-limit, 429-backoff и разбором ошибок."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from intelbit_floweon_connector_ozon.auth import OzonAuth
from intelbit_floweon_connector_ozon.exceptions import OzonApiError, OzonRateLimitError
from intelbit_floweon_connector_ozon.rate_limiter import OzonRateLimiter


class OzonHttpClient:
    """Общая логика вызова Ozon Seller API.

    Контракт ADR-006 (subprocess-aware): соединения не держим между вызовами —
    httpx.AsyncClient открывается и закрывается на каждый запрос.
    """

    def __init__(
        self,
        auth: OzonAuth,
        base_url: str,
        rate_limiter: OzonRateLimiter,
        _transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._rate_limiter = rate_limiter
        # _transport — для contract-тестов через httpx.ASGITransport (мок Ozon).
        self._transport = _transport

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Публичный POST для клиентов-композиций (например, OzonProductsClient)."""
        return await self._post(path, payload)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON на endpoint Ozon. Возвращает разобранное тело при code == 0."""
        await self._rate_limiter.acquire(path)
        url = f"{self._base_url}{path}"

        attempts = self._rate_limiter.max_retries
        last_retry_after = 0.0
        for attempt in range(attempts + 1):
            async with httpx.AsyncClient(timeout=30.0, transport=self._transport) as client:
                resp = await client.post(url, headers=self._auth.headers(), json=payload)

            if resp.status_code == 429:
                # Лимит на стороне Ozon — ждём Retry-After и повторяем.
                last_retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                if attempt < attempts:
                    await asyncio.sleep(last_retry_after)
                    continue
                raise OzonRateLimitError(
                    f"429 от Ozon на {path}: лимит не освободился за {attempts} повторов"
                )

            return _parse_response(resp)

        raise OzonRateLimitError(f"429 от Ozon на {path} (retry_after={last_retry_after})")


def _parse_retry_after(value: str | None) -> float:
    if not value:
        return 1.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 1.0


def _parse_response(resp: httpx.Response) -> dict[str, Any]:
    try:
        data: Any = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or (isinstance(data, dict) and data.get("code")):
        code = data.get("code", resp.status_code) if isinstance(data, dict) else resp.status_code
        message = data.get("message", resp.text) if isinstance(data, dict) else resp.text
        raise OzonApiError(code, message)
    if not isinstance(data, dict):
        raise OzonApiError(resp.status_code, "Ozon вернул не-JSON-объект")
    return data
