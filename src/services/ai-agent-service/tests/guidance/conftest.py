"""tests/guidance yardımcıları ve yerel fixture'lar (A9).

Double'lar yereldir ve ``is_test_double`` işaretlidir; double sonucu gerçek
sağlayıcı başarısı sayılmaz. Katalog/proje girdileri AÇIK test verisidir —
üretim onaylı kayıtları ``agent_core.adapters.static_records`` altındadır.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any, TypeVar

from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import (
    BudgetProfile,
    ExecutionContext,
    RouteDecision,
    RunIntent,
    compute_content_hash,
)
from agent_core.ports import ProgressSink
from agent_core.models import DomainProgress

T = TypeVar("T")

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)

ARTICLE_CONTENT = "# Kuyruk yönetimi\n\nBu makale asyncio kuyruk sınırını anlatır."


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    """Coroutine'i senkron test içinde çalıştırır."""
    return asyncio.run(coroutine)


def make_budget_profile(**overrides: Any) -> BudgetProfile:
    defaults: dict[str, Any] = dict(
        name="router-profile",
        max_model_calls=2,
        max_total_tokens=8000,
        max_duration_seconds=120.0,
    )
    defaults.update(overrides)
    return BudgetProfile(**defaults)


def make_guidance_context(question: str, *, language: str = "tr", **overrides: Any) -> ExecutionContext:
    """Makale bağlamı OLMAYAN genel rehberlik bağlamı."""
    defaults: dict[str, Any] = dict(
        run_id="run-1",
        conversation_id="conv-1",
        question=question,
        language=language,
        mode_preference="auto",
        budget_profile=make_budget_profile(),
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def make_article_snapshot(**overrides: Any):
    from agent_core.models import ArticleSnapshot

    defaults: dict[str, Any] = dict(
        article_id="post-1",
        slug="kuyruk-yonetimi",
        title="Kuyruk yönetimi",
        content=ARTICLE_CONTENT,
        content_hash=compute_content_hash(ARTICLE_CONTENT),
        article_revision=3,
        tags=["asyncio"],
        fetched_at=NOW,
    )
    defaults.update(overrides)
    return ArticleSnapshot(**defaults)


def make_article_bound_context(question: str, *, language: str = "tr", **overrides: Any) -> ExecutionContext:
    """İş birliği önerisinin bağlanacağı makale bağlamı (sözleşme: makale üçlüsü)."""
    snapshot = overrides.pop("article_snapshot", None) or make_article_snapshot()
    defaults: dict[str, Any] = dict(
        article_id=snapshot.article_id,
        article_revision=snapshot.article_revision,
        article_content_hash=snapshot.content_hash,
        article_snapshot=snapshot,
    )
    defaults.update(overrides)
    return make_guidance_context(question, language=language, **defaults)


def make_route(intent: RunIntent, *, mode: str = "fast", run_id: str = "run-1") -> RouteDecision:
    return RouteDecision(
        run_id=run_id,
        selected_mode=mode,
        intent=intent,
        brief_reason="a9 test kararı",
        decided_at=NOW,
    )


class ExplodingModelProvider:
    """Rehberlik/iş birliği akışının model çağırmadığını kanıtlayan double."""

    is_test_double = True

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, request, *, cancel=None):
        self.call_count += 1
        raise PortError(
            AgentErrorCode.PROVIDER_ERROR,
            "rehberlik akışı model çağırmamalıdır; bu double çağrıyı patlatır",
            port="ModelProvider",
        )


class FailingProfileRepository:
    """Port arızası simülasyonu: ``not_found`` (profil verisi yapılandırılmamış)."""

    is_test_double = True

    async def get_profile(self):
        raise PortError(
            AgentErrorCode.NOT_FOUND,
            "profil verisi yapılandırılmamış",
            port="ProfileRepository",
        )


class FailingProjectRepository:
    """Port arızası simülasyonu: ``provider_error``."""

    is_test_double = True

    async def list_projects(self):
        raise PortError(
            AgentErrorCode.PROVIDER_ERROR,
            "proje deposu yanıt vermiyor",
            port="ProjectRepository",
        )


class RecordingProgressSink:
    """İlerleme olaylarını kaydeden double (``ACTION_PROPOSED`` kanıtı için)."""

    is_test_double = True

    def __init__(self) -> None:
        self.events: list[DomainProgress] = []

    async def publish(self, event: DomainProgress) -> None:
        if not isinstance(event, DomainProgress):
            raise PortError(AgentErrorCode.VALIDATION_ERROR, "beklenmeyen olay tipi", port="ProgressSink")
        self.events.append(event)


def catalog_entry(article_id: str, title: str, url: str, topics: list[str]):
    """AÇIK test katalog kaydı üretir (üretim kataloğu adapters/static_records'ta boştur)."""
    from agent_core.guidance import ArticleCatalogEntry

    return ArticleCatalogEntry(article_id=article_id, title=title, url=url, topics=topics)


#: Açık test kataloğu — bağlantılar example.com'dur, gerçek yayın değildir.
TEST_CATALOG = [
    catalog_entry(
        "post-asyncio",
        "asyncio kuyruk sınırı yönetimi",
        "https://example.com/posts/asyncio-kuyruk",
        ["asyncio", "kuyruk", "python", "backpressure"],
    ),
    catalog_entry(
        "post-rabbitmq",
        "RabbitMQ ile güvenilir mesajlaşma",
        "https://example.com/posts/rabbitmq-mesajlasma",
        ["rabbitmq", "messaging", "outbox", "amqp"],
    ),
    catalog_entry(
        "post-langgraph",
        "LangGraph ile agent akışları",
        "https://example.com/posts/langgraph-agent",
        ["langgraph", "agent", "python", "state"],
    ),
]
