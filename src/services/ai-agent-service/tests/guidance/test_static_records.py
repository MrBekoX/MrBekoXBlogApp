"""Onaylı statik kayıt testleri (A9 gerçek veri kararı).

Kayıtlar yalnız repo içi GERÇEK kaynaklardan derlenir ve bu testler kaynak
değerlerini sabitler:

- ``src/frontend/blogapp-web/src/lib/site-config.ts`` — AUTHOR_NAME,
  AUTHOR_JOB_TITLE, AUTHOR_DESCRIPTION, SITE_URL, GITHUB_URL, TWITTER_URL,
  LINKEDIN_URL, SITE_KEYWORDS.
- ``src/backend/Presentation/API/Seo/SeoDocuments.cs`` — SiteName, AuthorName.
- ``README.md`` — platform tanımı ve teknoloji yığını.

Uydurma yasağı: deneyim/ücret/müsaitlik kayıtlarda TUTULMAZ; makale
kataloğu repoda gerçek yayın listesi olmadığından BOŞTUR.
"""

from __future__ import annotations

from agent_core.adapters import (
    APPROVED_ARTICLE_CATALOG,
    StaticProfileRepository,
    StaticProjectRepository,
)
from agent_core.adapters.test_doubles import FakeProfileRepository, FakeProjectRepository
from agent_core.ports import ProfileRepository, ProjectRepository


def test_static_profile_repository_satisfies_port_protocol() -> None:
    repo = StaticProfileRepository()
    assert isinstance(repo, ProfileRepository)


def test_static_project_repository_satisfies_port_protocol() -> None:
    repo = StaticProjectRepository()
    assert isinstance(repo, ProjectRepository)


def test_static_adapters_are_not_test_doubles() -> None:
    # Gerçek adaptör/test double ayrımı (A1 kabul ölçütü): üretim kökünde
    # is_test_double=True olamaz; static adaptörler açıkça False taşır.
    assert StaticProfileRepository.is_test_double is False
    assert StaticProjectRepository.is_test_double is False


def test_profile_record_matches_real_site_config_values() -> None:
    from agent_core.adapters import APPROVED_PROFILE

    assert APPROVED_PROFILE.name == "Berkay Kaplan"  # site-config AUTHOR_NAME
    assert APPROVED_PROFILE.job_title == "Software Developer"  # AUTHOR_JOB_TITLE
    # AUTHOR_DESCRIPTION birebir; ek cümle SiteDescription'dan (SeoDocuments.cs).
    assert APPROVED_PROFILE.description.startswith(
        "Backend geliştirme, yazılım mimarisi ve AI teknolojileri üzerine "
        "uzmanlaşmış yazılım geliştirici."
    )
    links = APPROVED_PROFILE.links
    assert links["site"] == "https://mrbekox.dev"  # SITE_URL
    assert links["github"] == "https://github.com/MrBekoX"  # GITHUB_URL
    assert links["x"] == "https://x.com/mrbeko_"  # TWITTER_URL
    assert links["linkedin"] == "https://www.linkedin.com/in/berkay-kaplan-133b35245/"  # LINKEDIN_URL
    # SITE_KEYWORDS'ten gerçek yetkinlikler (örnekler kaynakla sabitlenir).
    assert "clean architecture" in APPROVED_PROFILE.skills
    assert "AI agent" in APPROVED_PROFILE.skills
    assert "ASP.NET Core" in APPROVED_PROFILE.skills


def test_profile_record_contains_no_invented_missing_info() -> None:
    # Deneyim süresi/ücret/müsaitlik repoda OLMADIĞINDAN kayıtta da YOKTUR;
    # açıklama uydurma deneyim/ücret beyanı taşımaz.
    import re

    from agent_core.adapters import APPROVED_PROFILE

    text = f"{APPROVED_PROFILE.description} {' '.join(APPROVED_PROFILE.skills)}"
    assert re.search(r"\b\d+\s*y[ıi]l\b", text) is None
    for forbidden in ("ücret", "ücretlendirme", "müsait", "saatlik", "usd", "euro"):
        assert forbidden not in text.lower()


def test_project_records_are_real_repo_projects() -> None:
    from agent_core.adapters import APPROVED_PROJECTS

    names = [project.name for project in APPROVED_PROJECTS]
    assert names == ["MrBekoXBlogApp", "ai-agent-service", "BuildingBlocks.Messaging"]
    for project in APPROVED_PROJECTS:
        assert project.description, f"{project.name} açıklaması boş olamaz"
        assert project.technologies, f"{project.name} teknoloji listesi boş olamaz"
        for key, link in project.links.items():
            assert link, f"{project.name}/{key} bağlantısı boş olamaz"
    # README'den gerçek platform bağlantıları.
    platform = APPROVED_PROJECTS[0]
    assert platform.links["repo"] == "https://github.com/MrBekoX/MrBekoXBlogApp"
    assert platform.links["site"] == "https://mrbekox.dev"
    # README teknoloji yığınından gerçek örnekler.
    assert ".NET 10" in platform.technologies
    assert "Next.js 16" in platform.technologies
    assert "PostgreSQL" in platform.technologies


def test_approved_article_catalog_is_empty_until_real_content_sync() -> None:
    # Repoda gerçek yayınlanmış makale listesi yoktur; uydurma kayıt girilmez.
    # Öneri akışı boş katalogta dürüst "kullanılamaz" sonucu döner.
    assert APPROVED_ARTICLE_CATALOG == []


def test_static_repositories_return_copies_not_shared_state() -> None:
    import asyncio

    profile_repo = StaticProfileRepository()
    project_repo = StaticProjectRepository()

    async def mutate() -> None:
        profile = await profile_repo.get_profile()
        profile.skills.append("uydurma-beceri")
        projects = await project_repo.list_projects()
        projects[0].technologies.append("uydurma-teknoloji")

    asyncio.run(mutate())

    async def read():
        profile = await profile_repo.get_profile()
        projects = await project_repo.list_projects()
        return profile, projects

    fresh_profile, fresh_projects = asyncio.run(read())
    # Mutasyon paylaşılan onaylı kayda sızmaz (kopya döner).
    assert "uydurma-beceri" not in fresh_profile.skills
    assert "uydurma-teknoloji" not in fresh_projects[0].technologies
