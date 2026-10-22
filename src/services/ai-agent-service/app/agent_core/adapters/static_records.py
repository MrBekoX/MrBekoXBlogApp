"""Onaylı profil/proje kayıtları — A9 gerçek veri kararı + Who am I canonical kaynak.

PROFİL (Who am I, K2): legacy A9 ``ProfileSummary`` artık elle yazılmış ikinci
bir biyografi kopyası DEĞİLDİR; tek onaylı, sürümlü public profil kaynağından
(``src/content/author-profile``; ``agent_core.profile``) türetilir:

- açıklama: FAQ'taki üçüncü şahıs cevapları + eğitim satırı (≤4000 karakter);
- yetkinlikler: ``skills`` bölümünün maddeleri (niteleyiciler korunur,
  ör. "NestJS'i de inceledim"); SEO anahtar kelimeleri yetkinliğe
  DÖNÜŞTÜRÜLMEZ;
- bağlantılar: yayımlanmış ``contact_channels``.

Türetme tembeldir: kaynak eksik/bozuksa modül import'u ÇÖKMEZ; profil isteği
``ProfileSourceError`` (``config_error``) ile dürüstçe başarısız olur.

PROJE ve KATALOG kayıtları (değişmedi) repo içi gerçek kaynaklardan derlenir:

- ``README.md`` — platform tanım cümlesi ve teknoloji yığını.
- ``docs/ai-agent-plan/main-prompt.md`` — repo ve site URL'leri.
- ``docs/ai-agent-plan/decisions.md`` (D012) ve faz raporları — BuildingBlocks
  Messaging ve ai-agent-service açıklamaları.

Bilinçli EKSIKLER (uydurma yasağı): toplam deneyim süresi, ücret/fiyat,
müsaitlik kaynakta bulunmaz; böyle bir soru legacy yolda ``needs_input`` ile
karşılanır (``guidance.detect_missing_info_fields``). Makale önerisi kataloğu
repoda gerçek yayınlanmış makale listesi bulunmadığından BOŞTUR.
"""

from __future__ import annotations

import threading
from pathlib import Path

from ..guidance.models import ArticleCatalogEntry
from ..ports import ProfileSummary, ProjectRecord
from ..profile import CanonicalProfileRepository, resolve_profile_dir

__all__ = [
    "APPROVED_ARTICLE_CATALOG",
    "APPROVED_PROJECTS",
    "StaticProfileRepository",
    "StaticProjectRepository",
    "approved_profile",
]

_default_repository: CanonicalProfileRepository | None = None
_default_lock = threading.Lock()


def _canonical_repository() -> CanonicalProfileRepository:
    """Süreç genelinde paylaşılan canonical depo (yol bir kez çözülür).

    Raises:
        ProfileSourceError: canonical kaynak bulunamadı (``config_error``).
    """
    global _default_repository
    with _default_lock:
        if _default_repository is None:
            _default_repository = CanonicalProfileRepository(resolve_profile_dir())
        return _default_repository


def approved_profile() -> ProfileSummary:
    """Canonical kaynaktan türetilmiş onaylı profil özeti (legacy A9).

    Raises:
        ProfileSourceError: canonical kaynak eksik/bozuk/hash uyumsuz/public değil.
    """
    from ..profile import profile_summary_from_document

    return profile_summary_from_document(_canonical_repository().current_document())


def __getattr__(name: str):
    # Geriye dönük ad: ``APPROVED_PROFILE`` artık import anında değil, erişimde
    # canonical kaynaktan türetilir (bozuk kaynak import'u çökertmez).
    if name == "APPROVED_PROFILE":
        return approved_profile()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#: Onaylı proje kayıtları — MrBekoXBlogApp + repo içi gerçek projeler.
APPROVED_PROJECTS: list[ProjectRecord] = [
    ProjectRecord(
        name="MrBekoXBlogApp",
        description=(
            "A modern, full-stack blog platform with AI-powered content assistance, "
            "autonomous agent orchestration, and event-driven microservices — built "
            "with clean architecture principles. (README.md) Proje repo sahibi "
            "Sample Author tarafından geliştirilmektedir."
        ),
        technologies=[
            ".NET 10",
            "ASP.NET Core",
            "C#",
            "Next.js 16",
            "React 19",
            "TypeScript",
            "TailwindCSS",
            "PostgreSQL",
            "Redis",
            "RabbitMQ",
            "EF Core",
            "MediatR",
            "Python 3.13",
            "LangGraph",
        ],
        links={
            "repo": "https://github.com/MrBekoX/MrBekoXBlogApp",
            "site": "https://mrbekox.dev",
        },
    ),
    ProjectRecord(
        name="ai-agent-service",
        description=(
            "MrBekoXBlogApp'in Python/LangGraph agent çekirdeği: iş modelleri, port "
            "arayüzleri, deterministik router, makale soru-cevap, derin araştırma ve "
            "checkpoint/resume akışları; .NET backend ile RabbitMQ üzerinden "
            "haberleşir (docs/ai-agent-plan)."
        ),
        technologies=["Python 3.13", "LangGraph", "Pydantic v2", "aio-pika", "SQLAlchemy", "asyncpg", "Alembic"],
        links={
            "repo": "https://github.com/MrBekoX/MrBekoXBlogApp",
            "path": "src/services/ai-agent-service",
        },
    ),
    ProjectRecord(
        name="BuildingBlocks.Messaging",
        description=(
            "RabbitMQ.Client 7.x üzerine sıfırdan yazılan mesajlaşma building block'u: "
            "confirm+mandatory publisher, idempotent topology initializer, "
            "prefetch'li consumer (karar D012)."
        ),
        technologies=[".NET 10", "RabbitMQ.Client 7.2.2"],
        links={
            "repo": "https://github.com/MrBekoX/MrBekoXBlogApp",
            "path": "src/backend/BuildingBlocks/BuildingBlocks/Messaging",
        },
    ),
]

#: Onaylı makale önerisi kataloğu. Repoda gerçek yayınlanmış makale listesi
#: YOKTUR; uydurma kayıt girilmez. Öneri akışı boş katalogta dürüst
#: "kullanılamaz" sonucu döner; B8 içerik senkronu bağlandığında buraya
#: doğrulanmış kayıtlar beslenir.
APPROVED_ARTICLE_CATALOG: list[ArticleCatalogEntry] = []


class StaticProfileRepository:
    """Onaylı profil özetini okuyan gerçek adaptör (``ProfileRepository``).

    Varsayılan kaynak canonical profil kaynağıdır (``approved_profile``);
    test double DEĞİLDİR. ``profile`` verilirse o kayıt (kopyası) döner.
    ``directory`` verilirse o canonical dizin okunur. ``get_profile`` kaydın
    kopyasını döndürür; çağıran kaydı değiştiremez.

    Raises (``get_profile``):
        ProfileSourceError: canonical kaynak kullanılamıyor (``config_error``).
    """

    is_test_double = False

    def __init__(self, profile: ProfileSummary | None = None, *, directory: Path | None = None) -> None:
        self._profile = profile
        self._repository = CanonicalProfileRepository(directory) if directory is not None else None

    async def get_profile(self) -> ProfileSummary:
        if self._profile is not None:
            return self._profile.model_copy(deep=True)
        if self._repository is not None:
            return await self._repository.get_profile()
        return approved_profile()


class StaticProjectRepository:
    """Onaylı statik proje kayıtlarını listeleyen gerçek adaptör (``ProjectRepository``)."""

    is_test_double = False

    def __init__(self, projects: list[ProjectRecord] | None = None) -> None:
        self._projects = list(projects) if projects is not None else list(APPROVED_PROJECTS)

    async def list_projects(self) -> list[ProjectRecord]:
        return [project.model_copy(deep=True) for project in self._projects]
