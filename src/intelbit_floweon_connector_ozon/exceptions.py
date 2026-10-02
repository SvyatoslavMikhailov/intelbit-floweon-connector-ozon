"""Исключения коннектора Ozon."""

from __future__ import annotations


class OzonError(RuntimeError):
    """Базовая ошибка коннектора Ozon."""


class OzonApiError(OzonError):
    """Ozon Seller API вернул ошибку (HTTP 4xx/5xx или code != 0 в теле)."""

    def __init__(self, code: int | str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Ozon API error {code}: {message}")


class OzonRateLimitError(OzonError):
    """Лимит запросов исчерпан и retry не помог (429 после max_retries)."""


class WebhookValidationError(OzonError):
    """Входящий webhook не прошёл валидацию (IP-allowlist или secret)."""
