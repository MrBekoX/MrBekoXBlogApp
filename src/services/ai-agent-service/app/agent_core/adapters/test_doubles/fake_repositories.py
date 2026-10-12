"""Content/Profile/Project repository test double'ları."""

from __future__ import annotations

from ...errors import AgentErrorCode, PortError
from ...models import ArticleSnapshot
from ...ports import ProfileSummary, ProjectRecord

__all__ = ["FakeContentRepository", "FakeProfileRepository", "FakeProjectRepository"]


class FakeContentRepository:
    """Sözlük temelli makale deposu; ``not_found`` sözleşmesini uygular."""

    is_test_double = True

    def __init__(self, articles: dict[str, ArticleSnapshot] | None = None) -> None:
        self.articles = dict(articles or {})

    async def get_article(self, article_id: str) -> ArticleSnapshot:
        try:
            return self.articles[article_id]
        except KeyError:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"makale bulunamadı veya yayımlı değil: {article_id}",
                port="ContentRepository",
            ) from None


class FakeProfileRepository:
    """Sabit profil özeti döndüren test double."""

    is_test_double = True

    def __init__(self, profile: ProfileSummary | None = None) -> None:
        self.profile = profile or ProfileSummary(name="test-yazar", updated_at=None)
        self.call_count = 0

    async def get_profile(self) -> ProfileSummary:
        self.call_count += 1
        return self.profile


class FakeProjectRepository:
    """Sabit proje listesi döndüren test double."""

    is_test_double = True

    def __init__(self, projects: list[ProjectRecord] | None = None) -> None:
        self.projects = list(projects or [])

    async def list_projects(self) -> list[ProjectRecord]:
        return list(self.projects)
