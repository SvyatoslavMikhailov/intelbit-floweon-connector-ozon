"""Аутентификация Ozon Seller API: Client-Id + Api-Key headers."""

from dataclasses import dataclass


@dataclass
class OzonAuth:
    """Учётные данные для Ozon Seller API."""

    client_id: str
    api_key: str

    def headers(self) -> dict[str, str]:
        """Заголовки авторизации для каждого запроса к Ozon API."""
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }
