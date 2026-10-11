"""WebSearchProvider portu ve veri tipi.

Veri: kontrollü web arama sonuçları — A0 §5; A4 öncesi somut sağlayıcı kararı
gerektirir. Sonuç metinleri prompt'a girmeden önce boyut sınırına tabidir.

Hata türleri: ``validation_error`` (geçersiz sorgu/limit), ``config_error``,
``provider_error``, ``timeout``, ``cancelled``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field, PositiveInt

from ..models import BusinessModel, UtcDatetime
from .cancellation import CancellationToken

__all__ = ["WebSearchProvider", "WebSearchResult"]


class WebSearchResult(BusinessModel):
    """Port veri tipi: tek arama sonucu."""

    title: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=2048)
    snippet: str | None = Field(default=None, max_length=4000)
    retrieved_at: UtcDatetime


@runtime_checkable
class WebSearchProvider(Protocol):
    """Kontrollü web arama port; özel/ağ içi adreslere erişim uygulamada reddedilir."""

    async def search(
        self,
        query: str,
        *,
        max_results: PositiveInt = 5,
        cancel: CancellationToken | None = None,
    ) -> list[WebSearchResult]:
        """Sorgu için en fazla ``max_results`` sonuç döndürür.

        Raises:
            PortError: ``validation_error`` — boş sorgu; ``config_error`` —
                arama sağlayıcısı yapılandırılmamış; ``provider_error`` /
                ``timeout`` / ``cancelled``.
        """
        ...
