"""Onaylı kayıt testleri (A9 gerçek veri kararı + Who am I canonical kaynak).

Profil özeti tek canonical kaynaktan (``src/content/author-profile``)
türetilir; proje kayıtları repo içi GERÇEK kaynaklardan derlenir:

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


def test_profile_record_is_derived_from_canonical_profile_source() -> None:
    # Who am I (K2): legacy ProfileSummary canonical kaynaktan türetilir;
    # elle yazılmış ikinci biyografi kopyası ve SEO anahtar kelimesi yoktur.
    from agent_core.adapters import APPROVED_PROFILE
    from agent_core.profile import CanonicalProfileRepository, resolve_profile_dir

    document = CanonicalProfileRepository(resolve_profile_dir()).current_document()
    assert APPROVED_PROFILE.name == document.owner.name == "Sample Author"
    assert APPROVED_PROFILE.job_title is None  # canonical kaynakta unvan alanı yok; uydurulmaz
    assert len(APPROVED_PROFILE.description) <= 4000
    # Açıklama FAQ'taki üçüncü şahıs cevaplarından gelir (agent kendini Sample sanmaz).
    # Kalın FAQ soru satırları özete girmez; yalnız cevap metni.
    assert APPROVED_PROFILE.description.startswith("Örnekşehir'da yaşayan, .NET/C# ağırlıklı")
    assert "**" not in APPROVED_PROFILE.description and "kimdir?" not in APPROVED_PROFILE.description
    assert "Demo University" in APPROVED_PROFILE.description
    assert "Ben Sample Author" not in APPROVED_PROFILE.description
    links = APPROVED_PROFILE.links
    assert links["site"] == "https://example.invalid/author"
    assert links["github"] == "https://example.invalid/github"
    assert links["x"] == "https://example.invalid/social"
    assert links["linkedin"] == "https://www.example.invalid/linkedin"
    assert set(links.values()) == {channel.url for channel in document.privacy.contact_channels}
    # Yetkinlikler skills bölümünün maddeleridir; niteleyici ("inceledim") korunur.
    assert any(skill.startswith("Diller: C#") for skill in APPROVED_PROFILE.skills)
    assert any(".NET" in skill for skill in APPROVED_PROFILE.skills)
    # Eski SEO anahtar kelimeleri yetkinliğe dönüştürülmez.
    for seo_keyword in ("machine learning", "domain driven design", "mikroservis", "AI agent"):
        assert seo_keyword not in APPROVED_PROFILE.skills


def test_static_profile_repository_reads_explicit_canonical_directory(tmp_path) -> None:
    import asyncio
    import shutil

    from agent_core.profile import resolve_profile_dir

    target = tmp_path / "author-profile"
    shutil.copytree(resolve_profile_dir(), target)
    profile = asyncio.run(StaticProfileRepository(directory=target).get_profile())
    assert profile.name == "Sample Author"


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
