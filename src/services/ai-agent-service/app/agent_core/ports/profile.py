"""ProfileRepository portu ve veri tipi.

Veri: sahibin tanıtım verisi (ad, unvan, açıklama, sosyal linkler,
yetkinlikler) — A0 §5. Bugün doldurulabilir veri kaynağı yoktur; kaynak kararı
açık sorudur (W0 §6, açık soru 2). Port sözleşmesi A1'de sabittir.

Hata türleri: ``not_found``, ``config_error``, ``provider_error``, ``timeout``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from ..models import BusinessModel, Identifier, UtcDatetime

__all__ = ["ProfileRepository", "ProfileSummary"]


class ProfileSummary(BusinessModel):
    """Port veri tipi: iş modeli listesine dahil olmayan port içi tanıtım kaydı."""

    name: Identifier
    job_title: str | None = None
    description: str | None = Field(default=None, max_length=4000)
    links: dict[str, str] = {}
    skills: list[str] = []
    updated_at: UtcDatetime | None = None


@runtime_checkable
class ProfileRepository(Protocol):
    """Sahibin tanıtım verisini okuyan port."""

    async def get_profile(self) -> ProfileSummary:
        """Profil özetini döndürür.

        Raises:
            PortError: ``not_found`` — profil verisi yapılandırılmamış;
                ``config_error``/``provider_error``/``timeout``.
        """
        ...
