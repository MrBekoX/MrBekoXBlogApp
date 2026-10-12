"""LangGraph yürütücü: graph kurulumu, terminal sonuç ve checkpoint bağları.

Graph şekli planın derin araştırma mimarisidir (``01-agent-gelistirme-plani.md``
"Derin araştırma mimarisi"): hazırlık → plan → paralel alt görevler →
değerlendirme → (bütçe varsa sonraki tur) → rapor; fast/analysis doğrudan
yanıt node'una gider. Ortak bütçe ve iptal her node'un sınırındadır.

Terminal eşleme: ``CANCELLED`` → ``cancelled``; ``budget_exhausted`` /
``timeout`` → bulgu varsa mekanik kısmi raporla ``partial``, yoksa ``failed``;
diğer kodlar → ``failed``. Node'ların fırlattığı ``PortError`` graph'tan
dışarı taşınır ve burada tek terminal ``AgentOutcome``'a çevrilir.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from ..budget.guard import BudgetGuard
from ..budget.policy import BudgetPolicy, Deadline
from ..budget.store import PolicyBudgetStore
from ..errors import AgentErrorCode, PortError
from ..models import (
    AgentMode,
    AgentOutcome,
    DomainProgress,
    ExecutionContext,
    ProgressKind,
    RouteDecision,
    RunStatus,
    SourceScope,
)
from ..ports import BudgetStore, CancellationToken, CheckpointStore, ProgressSink
from ..state.artifacts import ArtifactStore, InMemoryArtifactStore
from ..state.events import NodeErrorRecord, usage_record_from_events
from ..state.state import AgentState, serialize_state
from .nodes import (
    GraphDeps,
    ResearchEffects,
    TaskContext,
    make_collect,
    make_finalize,
    make_plan,
    make_prepare,
    make_respond,
    make_subtask,
)

__all__ = ["GraphRunResult", "build_research_graph", "run_agent_graph"]

#: Checkpoint kimliği; A8 resume bu kimliği okur.
_STATE_CHECKPOINT_ID = "a2-state"


@dataclass
class GraphRunResult:
    """Bir graph yürütmesinin çıktısı: terminal sonuç, son state ve derlenmiş graph.

    ``compiled`` A8 resume/inspect akışları içindir; ``get_state``/``aget_state``
    bu graph üzerinden thread checkpoint'ine erişir [LG-PERSISTENCE#C1].
    """

    outcome: AgentOutcome
    state: AgentState
    compiled: object | None = None


def build_research_graph(deps: GraphDeps, *, checkpointer: BaseCheckpointSaver | None = None):
    """Node'ları ve koşullu geçişleri kurar; ``Send`` ile paralel worker açar."""
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("prepare", make_prepare(deps))
    graph.add_node("plan", make_plan(deps))
    graph.add_node("subtask", make_subtask(deps))
    graph.add_node("collect", make_collect(deps))
    graph.add_node("respond", make_respond(deps))
    graph.add_node("finalize", make_finalize(deps))

    def after_prepare(state: AgentState) -> str:
        return "plan" if deps.route.selected_mode is AgentMode.DEEP_RESEARCH else "respond"

    def dispatch(state: AgentState) -> list[Send] | str:
        """Bekleyen alt görevleri ``Send`` ile worker'lara dağıtır (oran: politika)."""
        pending = state.get("pending_subtasks") or []
        if not pending:
            return "finalize"
        return [Send("subtask", dict(task)) for task in pending]

    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", after_prepare, ["plan", "respond"])
    graph.add_conditional_edges("plan", dispatch, ["subtask", "finalize"])
    graph.add_edge("subtask", "collect")
    graph.add_conditional_edges("collect", dispatch, ["subtask", "finalize"])
    graph.add_edge("finalize", END)
    graph.add_edge("respond", END)

    config = {"checkpointer": checkpointer} if checkpointer is not None else {}
    return graph.compile(**config)


def _terminal_outcome(
    deps: GraphDeps, state: AgentState, error: PortError, elapsed: float
) -> AgentOutcome:
    """Port hatasını plan durumlarından birine çevirir (plan A2 durum ayrımı)."""
    usage = usage_record_from_events(deps.context.run_id, deps.tasks.take_events(), duration_seconds=elapsed)
    findings = list(state.get("findings", []))
    base = dict(
        selected_mode=deps.route.selected_mode,
        source_scope=SourceScope.ARTICLE_AND_WEB if deps.route.requires_web_search else SourceScope.ARTICLE,
        usage=usage,
    )
    if error.code is AgentErrorCode.CANCELLED:
        return AgentOutcome(status=RunStatus.CANCELLED, error_code=None, error_message=error.message, **base)
    if error.code in (AgentErrorCode.BUDGET_EXHAUSTED, AgentErrorCode.TIMEOUT) and findings:
        # Mekanik kısmi rapor: yalnız mevcut bulguların özeti; rapor dili A7'nindir.
        partial = "\n\n".join(f"- {finding.summary}" for finding in findings)
        answered = {finding.sub_question for finding in findings}
        unresolved = [q for q in state["plan"].sub_questions if q not in answered]
        return AgentOutcome(
            status=RunStatus.PARTIAL,
            report=partial,
            unresolved_questions=unresolved,
            error_code=error.code,
            error_message=error.message,
            **base,
        )
    return AgentOutcome(
        status=RunStatus.FAILED, error_code=error.code, error_message=error.message, **base
    )


async def _publish(
    progress: ProgressSink | None, run_id: str, kind: ProgressKind, message: str
) -> None:
    """İlerleme yayınlar; sink arızası akışı kesmez (port sözleşmesi)."""
    if progress is None:
        return
    event = DomainProgress(run_id=run_id, kind=kind, message=message, occurred_at=datetime.now(timezone.utc))
    try:
        await progress.publish(event)
    except PortError:
        return


async def _crash_state(app, config: dict, initial: AgentState) -> AgentState:
    """Çökme sonrası en iyi bilinen state'i döndürür.

    Checkpointer varsa son superstep değerleri okunur (tamamlanmış worker
    yazıları kaybolmaz); yoksa yalnız başlangıç state'i mevcuttur — tam
    kurtarma A8'in konusudur.
    """
    if not config:
        return initial
    try:
        snapshot = await app.aget_state(config)
    except Exception:  # noqa: BLE001 - kurtarma best-effort'tur; terminal sonuç yine üretilir
        return initial
    values = getattr(snapshot, "values", None)
    return dict(values) if values else initial


async def run_agent_graph(
    context: ExecutionContext,
    route: RouteDecision,
    *,
    effects: ResearchEffects,
    policy: BudgetPolicy | None = None,
    store: BudgetStore | None = None,
    artifacts: ArtifactStore | None = None,
    cancel: CancellationToken | None = None,
    checkpoint: CheckpointStore | None = None,
    langgraph_checkpointer: BaseCheckpointSaver | None = None,
    progress: ProgressSink | None = None,
) -> GraphRunResult:
    """Ortak state üzerinde graph'ı yürütür; terminal sonuç ve state döndürür.

    Raises:
        PortError: checkpoint yazımı arızası; terminal iş hataları
            ``AgentOutcome``'a çevrilir, yalnız depo arızaları yükselir.
    """
    policy = policy or BudgetPolicy()
    store = store or PolicyBudgetStore(policy)
    artifacts = artifacts or InMemoryArtifactStore()
    deadline = Deadline(policy.max_duration_seconds)
    guard = BudgetGuard(store, policy, context.run_id)
    tasks = TaskContext(
        run_id=context.run_id, guard=guard, artifacts=artifacts, cancel=cancel, deadline=deadline
    )
    deps = GraphDeps(
        context=context, route=route, effects=effects, policy=policy, guard=guard, tasks=tasks
    )
    initial: AgentState = {
        "schema_version": 1,
        "run_id": context.run_id,
        "context": context,
        "route": route,
        "article_revision": context.article_revision,
        "messages": list(context.conversation_history),
        "evidence": [],
        "findings": [],
        "usage_events": [],
        "errors": [],
        "artifact_refs": [],
        "pending_subtasks": [],
    }
    app = build_research_graph(deps, checkpointer=langgraph_checkpointer)
    config = {"configurable": {"thread_id": context.run_id}} if langgraph_checkpointer is not None else {}

    await _publish(progress, context.run_id, ProgressKind.RUN_STARTED, "graph yürütümü başladı")
    started = datetime.now(timezone.utc)
    try:
        final_state: AgentState = await app.ainvoke(initial, config=config)
        outcome = final_state.get("outcome")
        if outcome is None:  # pragma: no cover - graph tüm yolları outcome'a bağlar
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR, "graph terminal sonuç üretmedi", port="runner"
            )
    except PortError as error:
        final_state = await _crash_state(app, config, initial)
        outcome = _terminal_outcome(deps, final_state, error, deadline.elapsed())
        await _publish(progress, context.run_id, ProgressKind.VALIDATION_COMPLETED, f"terminal: {error.code.value}")
    except asyncio.CancelledError:
        final_state = await _crash_state(app, config, initial)
        outcome = _terminal_outcome(
            deps,
            final_state,
            PortError(AgentErrorCode.CANCELLED, "yürütüm iptal edildi", port="runner"),
            deadline.elapsed(),
        )

    final_state = dict(final_state)
    final_state["outcome"] = outcome
    if outcome.error_code is not None:
        # Terminal hata izi state'e yazılır; checkpoint ile kalıcı olur.
        terminal_errors = list(final_state.get("errors") or [])
        terminal_errors.append(
            NodeErrorRecord(
                error_id=f"terminal:{outcome.error_code.value}",
                node="runner",
                code=outcome.error_code.value,
                message=outcome.error_message or "",
                occurred_at=datetime.now(timezone.utc),
            )
        )
        final_state["errors"] = terminal_errors
    await _publish(
        progress, context.run_id, ProgressKind.GENERATION_COMPLETED,
        f"terminal sonuç: {outcome.status.value}",
    )
    if checkpoint is not None:
        payload = serialize_state(final_state)
        await checkpoint.save(context.run_id, _STATE_CHECKPOINT_ID, payload)
    return GraphRunResult(outcome=outcome, state=final_state, compiled=app)
