"""Graph node'ları ve etkiler sözleşmesi (plan A2).

Node sorumlulukları (plan A2: "Node'ların sorumluluklarını ve koşullu geçişleri
açıkça tanımla"):

- ``prepare``: bağlamı doğrular, içerik revizyonunu state'e yazar.
- ``plan``: alt soruları sınırlar içinde üretir, ilk araştırma turunu bütçeye yazar.
- ``subtask``: ``Send`` ile paralel yürütülen worker; dış çağrıları
  ``TaskContext.guarded`` ile bütçe/iptal sınırında koşar, sonuçları benzersiz
  kimlikle kanal birleştirmesine teslim edilir [LG-WORKFLOWS#C2].
- ``collect``: tur sonuçlarını değerlendirir; bütçe ve tur sınırına göre sonraki
  ``Send`` yığınını kurar veya bitirir.
- ``finalize``/``respond``: terminal AgentOutcome'u ve asistan mesajını yazar.

Gerçek plan/araştırma/rapor davranışı A4–A7'nin etkileridir; bu modül yalnız
sözleşmeyi ve yürütme mekaniğini tanımlar. Node hata türleri ortak
``PortError`` kodlarıdır: ``budget_exhausted`` (çağrı başlamaz),
``cancelled``/``timeout`` (canlılık), ``provider_error``/``timeout``
(``retryable=True`` ise guard sınırı içinde tekrar), ``stale_snapshot`` /
``validation_error`` / ``config_error`` (terminal, retry yok).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from ..budget.guard import BudgetGuard, CallResult, GuardedOutcome, assert_active
from ..budget.policy import BudgetPolicy, Deadline
from ..errors import AgentErrorCode, PortError
from ..models import (
    AgentOutcome,
    ConversationTurn,
    EvidenceItem,
    ExecutionContext,
    ResearchFinding,
    ResearchPlan,
    RouteDecision,
    RunStatus,
    SourceScope,
    compute_content_hash,
)

from ..ports import BudgetKind, CancellationToken
from ..state.artifacts import ArtifactRef, ArtifactStore
from ..state.events import NodeErrorRecord, UsageEvent, usage_record_from_events
from ..state.state import AgentState, SubtaskInput

__all__ = [
    "GraphDeps",
    "ReportDraft",
    "ResearchEffects",
    "SubtaskOutcome",
    "TaskContext",
    "assistant_turn",
    "make_collect",
    "make_finalize",
    "make_plan",
    "make_prepare",
    "make_respond",
    "make_subtask",
]


class TaskContext:
    """Node ve etkilerin bütçe/iptal/artifact erişimi; kullanım olaylarını toplar.

    Etkiler dış çağrılarını ``guarded`` ile koşar; olaylar otomatik toplanır,
    node çıktısına ``take_events`` ile karışır. Olay kimlikleri ``action_id``
    üzerinden kararlıdır; tekrar yürütme state'te kopya kullanım üretmez.
    """

    def __init__(
        self,
        *,
        run_id: str,
        guard: BudgetGuard,
        artifacts: ArtifactStore,
        cancel: CancellationToken | None = None,
        deadline: Deadline | None = None,
    ) -> None:
        self.run_id = run_id
        self.guard = guard
        self.artifacts = artifacts
        self.cancel = cancel
        self.deadline = deadline
        self._events: list[UsageEvent] = []

    def check_active(self) -> None:
        """Araç çağrısı sınırındaki canlılık kontrolü; etkiler çağrı öncesi çağırır."""
        assert_active(self.cancel, self.deadline)

    async def guarded(
        self,
        *,
        action_id: str,
        kind: BudgetKind,
        call: Callable[[int], Awaitable[CallResult]],
        token_estimate: int | None = None,
    ) -> GuardedOutcome:
        """Dış çağrıyı guard üzerinden yürütür ve olayları toplar.

        ``events_sink`` sayesinde istisna yollarındaki olaylar da (belirsiz
        kullanım, başarısız deneme) koleksiyona düşer ve node çıktısıyla
        state'e mergeslenir.
        """
        outcome = await self.guard.guarded(
            action_id=action_id,
            kind=kind,
            call=call,
            cancel=self.cancel,
            deadline=self.deadline,
            token_estimate=token_estimate,
            events_sink=self._events,  # olaylar istisna yollarında da buraya düşer
        )
        return outcome

    def take_events(self) -> list[UsageEvent]:
        events, self._events = self._events, []
        return events


@dataclass
class SubtaskOutcome:
    """Paralel worker'ın kanala bıraktığı sonuç; kimlikler kararlıdır.

    ``finding_id``/``evidence_id``/``artifact_id`` worker girdisiyle
    belirlenir (alt soru indeksi + içerik adresi); aynı görevin tekrar
    yürütülmesi aynı kimlikleri üretir ve reducer kopyayı düşürür.
    """

    sub_question: str
    sub_index: int
    round: int
    finding: ResearchFinding | None = None
    evidence: list[EvidenceItem] = field(default_factory=list)
    artifact_refs: list[ArtifactRef] = field(default_factory=list)


@dataclass
class ReportDraft:
    """Araştırma raporu taslağı; terminal sonucun metni ve belirsizlikleri."""

    text: str
    unresolved_questions: list[str] = field(default_factory=list)


class ResearchEffects(Protocol):
    """Graph'ın dış etkileri; gerçek davranış A4–A7 tarafından sağlanır.

    Tüm yöntemler ``TaskContext`` alır ve dış çağrılarını ``tasks.guarded``
    ile koşmakla yükümlüdür; aksi halde çağrı bütçe ve iptal denetimi
    dışında kalır.
    """

    def build_plan(self, question: str, tasks: TaskContext) -> Awaitable[Sequence[str]]:
        """Araştırma alt sorularını üretir; runner politika sınırına kırpar."""
        ...

    def run_subtask(self, task: SubtaskInput, tasks: TaskContext) -> Awaitable[SubtaskOutcome]:
        """Tek alt görevi yürütür; kanıt/bulgu kimlikleri kararlı olmalıdır."""
        ...

    def respond(self, question: str, tasks: TaskContext) -> Awaitable[str]:
        """fast/analysis cevabını üretir."""
        ...

    def report(
        self, question: str, findings: Sequence[ResearchFinding], tasks: TaskContext
    ) -> Awaitable[ReportDraft]:
        """Araştırma raporunu üretir; uydurma kaynak kimliği taşımamalıdır."""
        ...


@dataclass
class GraphDeps:
    """Node fabrikalarının paylaşılan bağımlılıkları."""

    context: ExecutionContext
    route: RouteDecision
    effects: ResearchEffects
    policy: BudgetPolicy
    guard: BudgetGuard
    tasks: TaskContext
    progress: Any | None = None  # ProgressSink | None (döngüsel import yok)


def assistant_turn(run_id: str, content: str) -> ConversationTurn:
    """Üretilen cevabın konuşma geçmişine eklenen asistan turu."""
    return ConversationTurn(role="assistant", content=content, created_at=datetime.now(timezone.utc))


def make_prepare(deps: GraphDeps) -> Callable[[AgentState], Awaitable[dict]]:
    """Bağlam doğrulama ve içerik revizyonu yazımı; dış çağrı yok."""

    async def prepare(state: AgentState) -> dict:
        assert_active(deps.tasks.cancel, deps.tasks.deadline)
        context = state["context"]
        snapshot = context.article_snapshot
        if snapshot is not None and compute_content_hash(snapshot.content) != snapshot.content_hash:
            raise PortError(
                AgentErrorCode.STALE_SNAPSHOT,
                "makale snapshot'ı hash'iyle uyuşmuyor",
                port="prepare",
            )
        return {"article_revision": context.article_revision}

    return prepare


def make_plan(deps: GraphDeps) -> Callable[[AgentState], Awaitable[dict]]:
    """Alt soruları sınırlar, ilk araştırma turunu bütçeye yazar."""

    async def plan(state: AgentState) -> dict:
        assert_active(deps.tasks.cancel, deps.tasks.deadline)
        context = state["context"]
        questions = list(await deps.effects.build_plan(context.question, deps.tasks))
        del questions[deps.policy.max_sub_questions:]
        if not questions:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "araştırma planı en az bir alt soru üretmelidir",
                port="plan",
            )
        round_events = await deps.guard.track(
            BudgetKind.RESEARCH_ROUND, "research-round:1"
        )  # ilk tur dahil (plan A2)
        research_plan = ResearchPlan(
            plan_id=f"plan-{context.run_id}",
            run_id=context.run_id,
            question=context.question,
            sub_questions=questions,
            max_search_calls=deps.policy.max_search_calls,
            max_source_pages=deps.policy.max_source_pages,
            max_research_rounds=deps.policy.max_research_rounds,
            max_parallel_subtasks=deps.policy.max_parallel_subtasks,
            requires_web_search=deps.route.requires_web_search,
            created_at=datetime.now(timezone.utc),
        )
        batch = [
            SubtaskInput(sub_question=q, sub_index=index, round=1)
            for index, q in enumerate(questions[: deps.policy.max_parallel_subtasks])
        ]
        return {
            "plan": research_plan,
            "research_round": 1,
            "pending_subtasks": batch,
            "usage_events": round_events + deps.tasks.take_events(),
        }

    return plan


def make_subtask(deps: GraphDeps) -> Callable[[SubtaskInput], Awaitable[dict]]:
    """Paralel worker: dış çağrıları bütçe/iptal sınırında koşar, sonuç yazar."""

    async def subtask(payload: SubtaskInput) -> dict:
        assert_active(deps.tasks.cancel, deps.tasks.deadline)  # node sınırı
        outcome = await deps.effects.run_subtask(payload, deps.tasks)
        assert_active(deps.tasks.cancel, deps.tasks.deadline)  # çağrı sonrası sınır
        update: dict[str, Any] = {
            "evidence": list(outcome.evidence),
            "usage_events": deps.tasks.take_events(),
        }
        if outcome.finding is not None:
            update["findings"] = [outcome.finding]
        if outcome.artifact_refs:
            update["artifact_refs"] = list(outcome.artifact_refs)
        return update

    return subtask


def _next_batch(deps: GraphDeps, state: AgentState) -> list[SubtaskInput]:
    """Bulgu eksik kalan alt sorulardan sıradaki ``Send`` yığınını kurar."""
    plan_model = state.get("plan")
    if plan_model is None:
        return []
    answered = {finding.sub_question for finding in state.get("findings", [])}
    remaining = [q for q in plan_model.sub_questions if q not in answered]
    return [
        SubtaskInput(
            sub_question=q,
            sub_index=plan_model.sub_questions.index(q),
            round=state.get("research_round", 1) + 1,
        )
        for q in remaining[: deps.policy.max_parallel_subtasks]
    ]


def make_collect(deps: GraphDeps) -> Callable[[AgentState], Awaitable[dict]]:
    """Tur değerlendirmesi: bütçe ve tur sınırına göre devam veya bitiş."""

    async def collect(state: AgentState) -> dict:
        assert_active(deps.tasks.cancel, deps.tasks.deadline)
        finished_round = state.get("research_round", 1)
        batch = _next_batch(deps, state)
        if not batch or finished_round >= deps.policy.max_research_rounds:
            return {"pending_subtasks": []}
        try:
            round_events = await deps.guard.track(
                BudgetKind.RESEARCH_ROUND, f"research-round:{finished_round + 1}"
            )
        except PortError as error:
            if error.code is AgentErrorCode.BUDGET_EXHAUSTED:
                # Bütçe bitişi: kısmi sonuç yolu; hata state'e kaydedilir.
                return {
                    "pending_subtasks": [],
                    "errors": [
                        NodeErrorRecord(
                            error_id=f"research-round:{finished_round + 1}:budget",
                            node="collect",
                            code=error.code.value,
                            message=error.message,
                            occurred_at=datetime.now(timezone.utc),
                        )
                    ],
                }
            raise
        return {
            "pending_subtasks": batch,
            "research_round": finished_round + 1,
            "usage_events": round_events,
        }

    return collect


def make_respond(deps: GraphDeps) -> Callable[[AgentState], Awaitable[dict]]:
    """fast/analysis yolu: cevabı üretir ve terminal sonucu yazar."""

    async def respond(state: AgentState) -> dict:
        assert_active(deps.tasks.cancel, deps.tasks.deadline)
        context = state["context"]
        answer = await deps.effects.respond(context.question, deps.tasks)
        fresh = deps.tasks.take_events()
        # Kullanım görünümü state kanalındaki tüm olaylardan kurulur (kopyalar
        # event_id ile düşer); paralel worker olayları yerel listeye bağlı değildir.
        usage = usage_record_from_events(
            context.run_id,
            list(state.get("usage_events", [])) + fresh,
            duration_seconds=deps.tasks.deadline.elapsed() if deps.tasks.deadline else 0.0,
        )
        scope = (
            SourceScope.ARTICLE_AND_WEB
            if deps.route.requires_web_search
            else SourceScope.ARTICLE if context.article_snapshot is not None else SourceScope.GENERAL
        )
        outcome = AgentOutcome(
            selected_mode=deps.route.selected_mode,
            status=RunStatus.COMPLETED,
            answer=answer,
            citations=[],
            source_scope=scope,
            unresolved_questions=[],
            usage=usage,
        )
        return {
            "outcome": outcome,
            "messages": [assistant_turn(context.run_id, answer)],
            "usage_events": fresh,
        }

    return respond


def make_finalize(deps: GraphDeps) -> Callable[[AgentState], Awaitable[dict]]:
    """Araştırma yolu: raporu üretir, tam/kısmi sonucu ve mesajı yazar."""

    async def finalize(state: AgentState) -> dict:
        assert_active(deps.tasks.cancel, deps.tasks.deadline)
        context = state["context"]
        findings = list(state.get("findings", []))
        draft = await deps.effects.report(context.question, findings, deps.tasks)
        fresh = deps.tasks.take_events()
        answered = {finding.sub_question for finding in findings}
        plan_model = state.get("plan")
        unresolved = [q for q in (plan_model.sub_questions if plan_model else []) if q not in answered]
        usage = usage_record_from_events(
            context.run_id,
            list(state.get("usage_events", [])) + fresh,
            duration_seconds=deps.tasks.deadline.elapsed() if deps.tasks.deadline else 0.0,
        )
        status = RunStatus.PARTIAL if unresolved else RunStatus.COMPLETED
        outcome = AgentOutcome(
            selected_mode=deps.route.selected_mode,
            status=status,
            report=draft.text,
            citations=[],
            source_scope=SourceScope.ARTICLE_AND_WEB,
            unresolved_questions=unresolved,
            usage=usage,
        )
        return {
            "outcome": outcome,
            "messages": [assistant_turn(context.run_id, draft.text)],
            "usage_events": fresh,
        }

    return finalize
