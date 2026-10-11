"""SourceReader portu ve veri tipi.

Veri: URL'den okunan temizlenmiş metin — A0 §5; A4 öncesi somut karar.
Uygulamalar yönlendirme ve DNS dahil özel/metadata adreslerine erişmemeli;
bu kontrol uygulamanın sorumluluğudur (ana prompt kritik kontroller).

Hata türleri: ``not_found`` (erişilemeyen/kaldırılmış kaynak), ``validation_error``
(yasak adres şeması/ağı), ``provider_error``, ``timeout``, ``cancelled``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from ..models import BusinessModel, UtcDatetime
from .cancellation import CancellationToken

__all__ = ["ReadSource", "SourceReader"]


class ReadSource(BusinessModel):
    """Port veri tipi: okunan tek kaynağın temizlenmiş metni."""

    url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    text: str = Field(min_length=1, max_length=500000)
    fetched_at: UtcDatetime
    content_type: str | None = None


@runtime_checkable
class SourceReader(Protocol):
    """Web kaynağı okuma port; dönen metin temizlenmiş düz metindir."""

    async def read(self, url: str, *, cancel: CancellationToken | None = None) -> ReadSource:
        """URL içeriğini okur.

        Raises:
            PortError: ``not_found`` — kaynak yok/erişilemez; ``validation_error``
                — özel/metadata adresi; ``provider_error``/``timeout``/``cancelled``.
        """
        ...
