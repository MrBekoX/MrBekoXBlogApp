"""ProfileRepository ve ProfileKnowledgeRepository portları.

``ProfileRepository`` (A1/A9): sahibin kısa tanıtım özeti (ad, açıklama,
sosyal linkler, yetkinlikler) — legacy v1 PROFILE yolu bunu bütün olarak
yazdırır. Who am I'dan itibaren üretim adaptörü bu özeti canonical profil
kaynağından (``src/content/author-profile``) türetir.

``ProfileKnowledgeRepository`` (Who am I, K5): pinlenebilir canonical profil
belgesine erişim. ``active_snapshot`` aktif sürüm kimliğini, ``load`` pinlenmiş
sürümün doğrulanmış belgesini verir; pinlenen sürüm aktif değilse veya kaynak
bozuksa ``ProfileSourceError`` (``config_error``) yükselir — başka sürüme
sessizce geçilmez. Uygulama: ``agent_core.profile.CanonicalProfileRepository``.

Hata türleri: ``not_found``, ``config_error``, ``provider_error``, ``timeout``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import Field

from ..models import BusinessModel, Identifier, ProfileSnapshotRef, UtcDatetime

if TYPE_CHECKING:  # döngüsel import yok: belge tipi yalnız tip denetiminde
    from ..profile.source import ProfileDocument

__all__ = ["ProfileKnowledgeRepository", "ProfileRepository", "ProfileSummary"]


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


@runtime_checkable
class ProfileKnowledgeRepository(Protocol):
    """Pinlenebilir canonical profil belgesine erişen port (Who am I RAG)."""

    def active_snapshot(self) -> ProfileSnapshotRef:
        """Aktif, doğrulanmış profil sürümünün gövdesiz kimliği.

        Raises:
            ProfileSourceError: kaynak eksik/bozuk/hash uyumsuz/public değil (``config_error``).
        """
        ...

    def load(self, snapshot: ProfileSnapshotRef) -> "ProfileDocument":
        """Pinlenmiş sürümün doğrulanmış belgesi.

        Raises:
            ProfileSourceError: kaynak kullanılamıyor veya pinlenen sürüm artık aktif değil.
        """
        ...
