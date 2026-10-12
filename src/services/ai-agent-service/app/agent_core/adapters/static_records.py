"""Onaylı statik profil/proje kayıtları — A9 gerçek veri kararı.

GERÇEK VERİ KAYNAKLARI (repoda doğrulanmış statik içerik; UYDURMA YOK):

- ``src/frontend/blogapp-web/src/lib/site-config.ts`` — ``AUTHOR_NAME``
  ("Berkay Kaplan"), ``AUTHOR_JOB_TITLE`` ("Software Developer"),
  ``AUTHOR_DESCRIPTION``, ``SITE_URL`` (https://mrbekox.dev),
  ``GITHUB_URL``, ``TWITTER_URL``, ``LINKEDIN_URL``, ``SITE_KEYWORDS``.
- ``src/backend/Presentation/API/Seo/SeoDocuments.cs`` — ``SiteName`` ("MrBekoX"),
  ``AuthorName``, ``SiteDescription``.
- ``README.md`` — platform tanım cümlesi ve teknoloji yığını (§Architecture,
  §Tech Stack).
- ``docs/ai-agent-plan/main-prompt.md`` — repo ve site URL'leri
  (github.com/MrBekoX/MrBekoXBlogApp, mrbekox.dev).
- ``docs/ai-agent-plan/decisions.md`` (D012) ve faz raporları — BuildingBlocks
  Messaging ve ai-agent-service açıklamaları.

Bilinçli EKSIKLER (uydurma yasağı): deneyim süresi, ücret/fiyat, müsaitlik
repoda hiçbir kaynakta bulunmadığı için bu kayıtlarda TUTULMAZ; böyle bir
soru ``needs_input`` ile karşılanır (``guidance.detect_missing_info_fields``).

Proje rehberi MrBekoXBlogApp'in kendisi ve repo içi gerçek projelerle
sınırlıdır. Makale önerisi kataloğu repoda gerçek yayınlanmış makale
listesi bulunmadığından BOŞTUR — öneri yalnız B8 içerik senkronundan
bağlanan onaylı katalogla üretilebilir; boş kataloğa karşı dürüst
"kullanılamaz" sonucu döner.
"""

from __future__ import annotations

from ..guidance.models import ArticleCatalogEntry
from ..ports import ProfileSummary, ProjectRecord

__all__ = [
    "APPROVED_ARTICLE_CATALOG",
    "StaticProfileRepository",
    "StaticProjectRepository",
]

#: Onaylı profil kaydı — yukarıdaki kaynaklardan birebir derlenmiştir.
APPROVED_PROFILE = ProfileSummary(
    name="Berkay Kaplan",
    job_title="Software Developer",
    description=(
        "Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine "
        "uzmanlaşmış yazılım geliştirici. Yazılım geliştirme yolculuğunda "
        "öğrendiklerini, teknik notları ve proje deneyimlerini mrbekox.dev'de paylaşıyor."
    ),
    links={
        "site": "https://mrbekox.dev",
        "github": "https://github.com/MrBekoX",
        "x": "https://x.com/mrbeko_",
        "linkedin": "https://www.linkedin.com/in/berkay-kaplan-133b35245/",
    },
    skills=[
        # site-config.ts SITE_KEYWORDS (gerçek SEO anahtar kelimeleri)
        "backend development",
        "yazılım mimarisi",
        "software architecture",
        "AI agent",
        "artificial intelligence",
        "mikroservis",
        "microservices",
        "sistem tasarımı",
        "system design",
        "machine learning",
        ".NET",
        "ASP.NET Core",
        "C#",
        "Python",
        "onion architecture",
        "clean architecture",
        "CQRS",
        "domain driven design",
    ],
    updated_at=None,
)

#: Onaylı proje kayıtları — MrBekoXBlogApp + repo içi gerçek projeler.
APPROVED_PROJECTS: list[ProjectRecord] = [
    ProjectRecord(
        name="MrBekoXBlogApp",
        description=(
            "A modern, full-stack blog platform with AI-powered content assistance, "
            "autonomous agent orchestration, and event-driven microservices — built "
            "with clean architecture principles. (README.md) Proje repo sahibi "
            "Berkay Kaplan tarafından geliştirilmektedir."
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
    """Onaylı statik profil kaydını okuyan gerçek adaptör (``ProfileRepository``).

    Kayıtlar modül docstring'inde listelenen repo içi gerçek kaynaklardan
    derlenmiştir; test double DEĞİLDİR. ``get_profile`` kaydın kopyasını
    döndürür; çağıran kaydı değiştiremez.
    """

    is_test_double = False

    def __init__(self, profile: ProfileSummary | None = None) -> None:
        self._profile = profile if profile is not None else APPROVED_PROFILE

    async def get_profile(self) -> ProfileSummary:
        return self._profile.model_copy(deep=True)


class StaticProjectRepository:
    """Onaylı statik proje kayıtlarını listeleyen gerçek adaptör (``ProjectRepository``)."""

    is_test_double = False

    def __init__(self, projects: list[ProjectRecord] | None = None) -> None:
        self._projects = list(projects) if projects is not None else list(APPROVED_PROJECTS)

    async def list_projects(self) -> list[ProjectRecord]:
        return [project.model_copy(deep=True) for project in self._projects]
