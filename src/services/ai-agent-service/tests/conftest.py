"""Test fabrikaları ve yardımcılar.

Async giriş noktaları pytest-asyncio gerektirmeden ``run()`` ile çağrılır:
paketin test bağımlılığı yalnız pytest + pydantic'tir.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any, TypeVar

from agent_core.models import (
    ActionProposal,
    AgentMode,
    AgentOutcome,
    ArticleChunk,
    ArticleSnapshot,
    BudgetProfile,
    DomainProgress,
    ExecutionContext,
    EvidenceItem,
    ProgressKind,
    ResearchFinding,
    ResearchPlan,
    RouteDecision,
    RunStatus,
    SourceReference,
    SourceScope,
    UsageRecord,
    ValidatedActionResult,
    compute_content_hash,
)

T = TypeVar("T")

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)

ARTICLE_CONTENT = "# Merhaba Dünya\n\nBu makale Python tip ipuçlarını anlatır."


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    """Coroutine'i senkron test içinde çalıştırır."""
    return asyncio.run(coroutine)


def make_snapshot(**overrides: Any) -> ArticleSnapshot:
    content = overrides.pop("content", ARTICLE_CONTENT)
    defaults: dict[str, Any] = dict(
        article_id="post-1",
        slug="merhaba-dunya",
        title="Merhaba Dünya",
        content=content,
        content_hash=compute_content_hash(content),
        article_revision=3,
        tags=["python"],
        fetched_at=NOW,
    )
    defaults.update(overrides)
    return ArticleSnapshot(**defaults)


def make_context(**overrides: Any) -> ExecutionContext:
    snapshot = overrides.pop("article_snapshot", None)
    defaults: dict[str, Any] = dict(
        run_id="run-1",
        conversation_id="conv-1",
        question="Bu makalede hangi konu işleniyor?",
        language="tr",
        mode_preference="auto",
        budget_profile=BudgetProfile(
            name="default",
            max_model_calls=2,
            max_total_tokens=8000,
            max_duration_seconds=120.0,
        ),
    )
    defaults.update(overrides)
    if snapshot is not None:
        defaults.setdefault("article_id", snapshot.article_id)
        defaults.setdefault("article_revision", snapshot.article_revision)
        defaults.setdefault("article_content_hash", snapshot.content_hash)
        defaults.setdefault("article_snapshot", snapshot)
    return ExecutionContext(**defaults)


def make_route(**overrides: Any) -> RouteDecision:
    defaults: dict[str, Any] = dict(
        run_id="run-1",
        selected_mode=AgentMode.FAST,
        reason="kısa ve tekil soru",
        requires_web_search=False,
        decided_at=NOW,
    )
    defaults.update(overrides)
    return RouteDecision(**defaults)


def make_usage(**overrides: Any) -> UsageRecord:
    defaults: dict[str, Any] = dict(
        run_id="run-1",
        model_calls=1,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        duration_seconds=0.5,
        recorded_at=NOW,
    )
    defaults.update(overrides)
    return UsageRecord(**defaults)


def make_action_proposal(**overrides: Any) -> ActionProposal:
    defaults: dict[str, Any] = dict(
        proposal_id="prop-1",
        run_id="run-1",
        article_id="post-1",
        article_revision=3,
        base_content_hash=compute_content_hash(ARTICLE_CONTENT),
        summary="Giriş paragrafı düzeltildi",
        proposed_content="# Merhaba Dünya\n\nDüzeltilmiş giriş.",
        created_at=NOW,
    )
    defaults.update(overrides)
    return ActionProposal(**defaults)


def make_outcome(**overrides: Any) -> AgentOutcome:
    defaults: dict[str, Any] = dict(
        selected_mode=AgentMode.FAST,
        status=RunStatus.COMPLETED,
        answer="Makale Python tip ipuçlarını anlatıyor.",
        citations=[],
        source_scope=SourceScope.ARTICLE,
        unresolved_questions=[],
        usage=make_usage(),
    )
    defaults.update(overrides)
    return AgentOutcome(**defaults)


def make_chunk(**overrides: Any) -> ArticleChunk:
    defaults: dict[str, Any] = dict(
        article_id="post-1",
        article_revision=3,
        chunk_index=0,
        content=ARTICLE_CONTENT,
        heading="Merhaba Dünya",
        char_start=0,
        char_end=len(ARTICLE_CONTENT),
    )
    defaults.update(overrides)
    return ArticleChunk(**defaults)


def make_article_reference(**overrides: Any) -> SourceReference:
    defaults: dict[str, Any] = dict(
        kind="article",
        article_id="post-1",
        article_revision=3,
        chunk_index=0,
        title="Merhaba Dünya",
    )
    defaults.update(overrides)
    return SourceReference(**defaults)


def make_web_reference(**overrides: Any) -> SourceReference:
    defaults: dict[str, Any] = dict(
        kind="web",
        url="https://example.com/guide",
        accessed_at=NOW,
        title="Kılavuz",
    )
    defaults.update(overrides)
    return SourceReference(**defaults)


def make_evidence(**overrides: Any) -> EvidenceItem:
    defaults: dict[str, Any] = dict(
        evidence_id="ev-1",
        source=make_article_reference(),
        excerpt="Python tip ipuçları 3.5'te geldi.",
        collected_at=NOW,
    )
    defaults.update(overrides)
    return EvidenceItem(**defaults)


def make_plan(**overrides: Any) -> ResearchPlan:
    defaults: dict[str, Any] = dict(
        plan_id="plan-1",
        run_id="run-1",
        question="Python tip ipuçlarının güncel durumu nedir?",
        sub_questions=["PEP 695 öncesi ve sonrası farkları nelerdir?"],
        created_at=NOW,
    )
    defaults.update(overrides)
    return ResearchPlan(**defaults)


def make_finding(**overrides: Any) -> ResearchFinding:
    defaults: dict[str, Any] = dict(
        finding_id="find-1",
        run_id="run-1",
        sub_question="PEP 695 öncesi ve sonrası farkları nelerdir?",
        summary="Yeni söz dizimi type alias'ları sadeleştiriyor.",
        confidence="medium",
        evidence_ids=["ev-1"],
        created_at=NOW,
    )
    defaults.update(overrides)
    return ResearchFinding(**defaults)


def make_progress(**overrides: Any) -> DomainProgress:
    defaults: dict[str, Any] = dict(
        run_id="run-1",
        kind=ProgressKind.MODE_SELECTED,
        message="mod seçildi: fast",
        occurred_at=NOW,
    )
    defaults.update(overrides)
    return DomainProgress(**defaults)


def make_validated_result(**overrides: Any) -> ValidatedActionResult:
    defaults: dict[str, Any] = dict(
        proposal_id="prop-1",
        run_id="run-1",
        outcome="accepted",
        applied_article_revision=4,
        validated_at=NOW,
    )
    defaults.update(overrides)
    return ValidatedActionResult(**defaults)
