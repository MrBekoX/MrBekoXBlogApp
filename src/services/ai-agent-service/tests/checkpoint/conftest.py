"""tests/checkpoint yardımcıları ve yerel fixture'lar (A8).

Model/iptal double'ları yereldir ve ``is_test_double`` işaretlidir; double
sonucu gerçek sağlayıcı başarısı sayılmaz. State fabrikaları tests/state ve
kök conftest kalıplarını izler; kök conftest'e dokunulmaz.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Coroutine, TypeVar

from agent_core.ports import CancellationToken, ModelRequest, ModelResponse, ModelUsage
from agent_core.state import STATE_SCHEMA_VERSION
from agent_core.state.artifacts import make_artifact_ref
from agent_core.state.events import UsageEvent, UsageEventKind
from agent_core.state.state import AgentState
from agent_core.models import (
    AgentMode,
    BudgetProfile,
    EvidenceItem,
    ExecutionContext,
    ResearchFinding,
    ResearchPlan,
    RouteDecision,
    SourceReference,
)

T = TypeVar("T")

NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)
ARTICLE_CONTENT_V3 = "# Kontrol sürümü r3\n\nBu makale broker hata sınıflarını anlatır."
ARTICLE_CONTENT_V4 = "# Güncel sürüm r4\n\nBu makale broker hata sınıflarını güncel API ile anlatır."


def run(coroutine: Coroutine[Any, Any, T]) -> T:
    """Coroutine'i senkron test içinde çalıştırır."""
    return asyncio.run(coroutine)


def make_budget_profile(**overrides: Any) -> BudgetProfile:
    defaults: dict[str, Any] = dict(
        name="test",
        max_model_calls=4,
        max_total_tokens=10_000,
        max_duration_seconds=60.0,
    )
    defaults.update(overrides)
    return BudgetProfile(**defaults)


def make_state(run_id: str = "run-a8") -> AgentState:
    """Kanıt/bulgu/alt görev/kullanım olayı taşıyan ortak graph state'i."""
    context = ExecutionContext(
        run_id=run_id,
        conversation_id="conv-a8",
        question="broker hata sınıfları nelerdir?",
        language="tr",
        mode_preference="deep_research",
        budget_profile=make_budget_profile(),
    )
    web_evidence = EvidenceItem(
        evidence_id="ev-web-1",
        source=SourceReference(kind="web", url="https://example.com/spec", accessed_at=NOW),
        excerpt="web kanıtı",
        collected_at=NOW,
    )
    article_evidence = EvidenceItem(
        evidence_id="ev-art-1",
        source=SourceReference(kind="article", article_id="post-1", article_revision=3, chunk_index=0),
        excerpt="makale kanıtı",
        collected_at=NOW,
    )
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "run_id": run_id,
        "context": context,
        "route": RouteDecision(
            run_id=run_id,
            selected_mode=AgentMode.DEEP_RESEARCH,
            reason="güncellik gerektiren soru",
            requires_web_search=True,
            decided_at=NOW,
        ),
        "article_revision": 3,
        "plan": ResearchPlan(
            plan_id="plan-a8",
            run_id=run_id,
            question="broker hata sınıfları nelerdir?",
            sub_questions=["S1: türler", "S2: sınırlar"],
            created_at=NOW,
        ),
        "pending_subtasks": [{"sub_question": "S2: sınırlar", "sub_index": 1, "round": 1}],
        "research_round": 1,
        "messages": [],
        "evidence": [web_evidence, article_evidence],
        "findings": [
            ResearchFinding(
                finding_id="find-1",
                run_id=run_id,
                sub_question="S1: türler",
                summary="tür özeti",
                confidence="medium",
                evidence_ids=["ev-art-1"],
                created_at=NOW,
            )
        ],
        "usage_events": [],
        "errors": [],
        "artifact_refs": [make_artifact_ref("source_page", "sayfa gövdesi", created_at=NOW)],
    }


def make_usage_event(event_id: str, action_id: str, tokens: int = 10) -> UsageEvent:
    return UsageEvent(
        event_id=event_id,
        run_id="run-a8",
        action_id=action_id,
        kind=UsageEventKind.MODEL_CALL,
        prompt_tokens=tokens,
        completion_tokens=tokens // 2,
        total_tokens=tokens + tokens // 2,
        recorded_at=NOW,
    )


class SlowModelProvider:
    """Belirtilen süre kadar bekleyip yanıt döndüren model double'ı (deadline testi)."""

    is_test_double = True

    def __init__(self, delay_seconds: float, response_text: str = "geç yanıt") -> None:
        self._delay = delay_seconds
        self._text = response_text
        self.call_count = 0

    async def complete(
        self, request: ModelRequest, *, cancel: CancellationToken | None = None
    ) -> ModelResponse:
        self.call_count += 1
        await asyncio.sleep(self._delay)
        return ModelResponse(
            text=self._text,
            model_name="slow-model",
            usage=ModelUsage(prompt_tokens=5, completion_tokens=5),
            finished_at=datetime.now(timezone.utc),
        )


class Stopwatch:
    """Monotonik saatle kısa süre ölçümü."""

    def __init__(self) -> None:
        self._started = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._started
