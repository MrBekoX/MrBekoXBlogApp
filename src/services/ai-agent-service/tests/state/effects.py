"""A2 test yardımcıları: politikalar, bağlam fabrikaları ve deterministik etkiler.

Bu modül bilinçli olarak ``conftest`` ADINI taşımaz: pytest importmodu altında
kök ``tests/conftest.py`` ile sys.modules çakışması ortam tuzasıdır. Test
dosyaları buradan ``import effects`` ile kullanır.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from agent_core.budget import BudgetPolicy, CallResult
from agent_core.errors import AgentErrorCode, PortError
from agent_core.graph import ReportDraft, SubtaskOutcome, TaskContext
from agent_core.models import (
    AgentMode,
    BudgetProfile,
    EvidenceItem,
    ExecutionContext,
    ResearchFinding,
    RouteDecision,
    SourceReference,
)
from agent_core.ports import BudgetKind

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


def make_policy(**overrides: Any) -> BudgetPolicy:
    """Test politikası: plan önerileri taban, gerekirse daraltılır."""
    defaults: dict[str, Any] = dict(
        max_sub_questions=4,
        max_search_calls=8,
        max_source_pages=12,
        max_research_rounds=2,
        max_parallel_subtasks=3,
        max_model_calls=16,
        max_total_tokens=50_000,
        max_tool_attempts=24,
        max_duration_seconds=60.0,
        max_attempts_per_action=2,
    )
    defaults.update(overrides)
    return BudgetPolicy(**defaults)


def make_run_context(**overrides: Any) -> ExecutionContext:
    """Derin araştırma bağlamı; snapshot'suz (web merkezli akış)."""
    defaults: dict[str, Any] = dict(
        run_id="run-a2",
        conversation_id="conv-a2",
        question="Python tip ipuçlarının güncel durumu nedir, araştır ve karşılaştır",
        language="tr",
        mode_preference="deep_research",
        budget_profile=BudgetProfile(
            name="test",
            max_model_calls=8,
            max_total_tokens=50_000,
            max_tool_calls=24,
            max_web_search_calls=8,
            max_duration_seconds=60.0,
        ),
    )
    defaults.update(overrides)
    return ExecutionContext(**defaults)


def make_route(context: ExecutionContext, mode: AgentMode = AgentMode.DEEP_RESEARCH) -> RouteDecision:
    return RouteDecision(
        run_id=context.run_id,
        selected_mode=mode,
        reason="test kararı",
        requires_web_search=mode is AgentMode.DEEP_RESEARCH,
        decided_at=NOW,
    )


def ok(value: Any, usage=None):
    """Başarılı dış çağrı double'ı üretir."""

    async def call(attempt: int) -> CallResult:
        return CallResult(value=value, usage=usage)

    return call


class MutableToken:
    """Test için iptal edilebilen CancellationToken double'ı."""

    is_test_double = True

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None

    def cancel(self, reason: str = "test iptali") -> None:
        self._cancelled = True
        self._reason = reason

    def is_cancelled(self) -> bool:
        return self._cancelled

    def reason(self) -> str | None:
        return self._reason

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise PortError(AgentErrorCode.CANCELLED, self._reason or "iptal", port="test")


class ScriptedEffects:
    """Deterministik etkiler: her alt görev arama + okuma + model çağrısı yapar.

    Çağrı günlüğü tutar; iptal/deadline senaryolarında "hangi çağrı başladı"
    iddiası bu günlük üzerinden kurulur. ``on_subtask`` kancası testin alt
    görev girişinde davranış değiştirmesine izin verir.
    """

    def __init__(
        self,
        *,
        sub_questions: Sequence[str] = ("S1", "S2", "S3", "S4", "S5"),
        on_subtask=None,
        page_size: int = 4000,
    ) -> None:
        self.sub_questions = list(sub_questions)
        self.on_subtask = on_subtask
        self.page_size = page_size
        self.started_calls: list[str] = []
        self.completed_calls: list[str] = []
        self.run_subtasks = 0

    async def build_plan(self, question: str, tasks: TaskContext) -> list[str]:
        return self.sub_questions

    async def run_subtask(self, task, tasks: TaskContext) -> SubtaskOutcome:
        self.run_subtasks += 1
        index = task["sub_index"]
        if self.on_subtask is not None:
            await self.on_subtask(task, tasks)
        await tasks.guarded(
            action_id=f"subtask:{index}:search",
            kind=BudgetKind.WEB_SEARCH_CALL,
            call=self._tracked(f"subtask:{index}:search", ok([f"hit-{index}"])),
        )
        page = f"sayfa içeriği {'x' * self.page_size} alt-{index}"
        ref = tasks.artifacts.put(
            tasks.run_id, "source_page", page, created_at=datetime.now(timezone.utc)
        )
        await tasks.guarded(
            action_id=f"subtask:{index}:read",
            kind=BudgetKind.SOURCE_PAGE_READ,
            call=self._tracked(f"subtask:{index}:read", ok(ref)),
        )
        await tasks.guarded(
            action_id=f"subtask:{index}:answer",
            kind=BudgetKind.MODEL_CALL,
            token_estimate=50,
            call=self._tracked(f"subtask:{index}:answer", ok("bulgu")),
        )
        evidence = EvidenceItem(
            evidence_id=f"ev-{index}",
            source=SourceReference(kind="web", url=f"https://example.com/{index}", accessed_at=NOW),
            excerpt="kanıt metni",
            collected_at=NOW,
        )
        finding = ResearchFinding(
            finding_id=f"find-{index}",
            run_id=tasks.run_id,
            sub_question=task["sub_question"],
            summary=f"bulgu {index}",
            confidence="medium",
            evidence_ids=[evidence.evidence_id],
            created_at=NOW,
        )
        return SubtaskOutcome(
            sub_question=task["sub_question"],
            sub_index=index,
            round=task["round"],
            finding=finding,
            evidence=[evidence],
            artifact_refs=[ref],
        )

    async def respond(self, question: str, tasks: TaskContext) -> str:
        outcome = await tasks.guarded(
            action_id="respond:answer",
            kind=BudgetKind.MODEL_CALL,
            token_estimate=40,
            call=self._tracked("respond:answer", ok("test cevabı")),
        )
        return str(outcome.value)

    async def report(
        self, question: str, findings: Sequence[ResearchFinding], tasks: TaskContext
    ) -> ReportDraft:
        await tasks.guarded(
            action_id="final:report",
            kind=BudgetKind.MODEL_CALL,
            token_estimate=80,
            call=self._tracked("final:report", ok("birleşik rapor")),
        )
        return ReportDraft(text="birleşik rapor")

    def _tracked(self, name: str, call):
        async def wrapper(attempt: int):
            self.started_calls.append(name)
            result = await call(attempt)
            self.completed_calls.append(name)
            return result

        return wrapper


def run_graph(context, route, effects, **kwargs):
    """Graph yürütümünü senkron test içinde koşturur."""

    async def _run():
        from agent_core.graph import run_agent_graph

        return await run_agent_graph(context, route, effects=effects, **kwargs)

    return asyncio.run(_run())
