"""ProjectRepository portu ve veri tipi.

Veri: proje kayıtları (ad, açıklama, teknolojiler, linkler) — A0 §5.
Bugün repoda proje verisi hiçbir yerde yoktur (A0 §3); port sözleşmesi
veri kaynağı kararından bağımsız sabitlenir.

Hata türleri: ``not_found``, ``config_error``, ``provider_error``, ``timeout``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from ..models import BusinessModel, Identifier

__all__ = ["ProjectRecord", "ProjectRepository"]


class ProjectRecord(BusinessModel):
    """Port veri tipi: tek bir portfolyo projesi kaydı."""

    name: Identifier
    description: str | None = Field(default=None, max_length=4000)
    technologies: list[str] = []
    links: dict[str, str] = {}


@runtime_checkable
class ProjectRepository(Protocol):
    """Proje kayıtlarını listeleyen port."""

    async def list_projects(self) -> list[ProjectRecord]:
        """Projeleri döndürür; boş liste geçerli sonuçtur.

        Raises:
            PortError: ``config_error``/``provider_error``/``timeout``.
        """
        ...
