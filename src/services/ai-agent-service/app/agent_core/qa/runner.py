"""Makale soru-cevap graph yürütücüsü (plan A4).

Graph şekli plan A4'ün node sorumluluklarını izler ve yeterlilik döngüsü
koşullu graph kenarıyla kurulur [LG-RAG#C1]:

    START → validate → retrieve → evaluate ─┬─ (yeterli) ─────→ generate → control → finalize → END
                                            ├─ (düzenleme) ───→ retrieve
                                            └─ (yetersiz) ────→ finalize

Web erişimi bu graph'ta yoktur: bağımlılık kümesinde web portu bile
bulunmaz (plan A4: "Bu aşamada web araçlarını çalıştırma").

Terminal eşleme: ``CANCELLED`` → ``cancelled``; diğer ``PortError`` kodları
→ ``failed``. QA akışında kısmi rapor yolu yoktur; bütçe/süre bitimi
yanıtsız kalmaktan iyiye ``failed`` terminalidir (derin araştırmanın
``partial`` yolu A6–A7'nindir). Node'ların fırlattığı ``PortError`` graph'tan
dışarı taşınır ve burada tek terminal ``AgentOutcome``'a çevrilir.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..budget.guard import BudgetGuard
from ..budget.policy import BudgetPolicy, Deadline
from ..budget.store import PolicyBudgetStore
from ..errors import AgentErrorCode, PortError
from ..graph.nodes import TaskContext
from ..models import AgentOutcome, ExecutionContext, RouteDecision, RunStatus, SourceScope
from ..ports import BudgetStore, CancellationToken, ProgressSink
from ..state.artifacts import ArtifactStore, InMemoryArtifactStore
from ..state.events import usage_record_from_events
from .models import QaFlowConfig, QaRunResult
from .nodes import (
    QaDeps,
    after_evaluate,
    make_control,
    make_evaluate,
    make_finalize,
    make_generate,
    make_retrieve,
    make_validate,
    build_retrieval_entry_query,
)
from .retrieval import ArticleRetriever
from .state import QaState

__all__ = ["build_article_qa_graph", "run_article_qa"]


def qa_policy_for(profile, config: QaFlowConfig) -> BudgetPolicy:
    """Bütçe profilini QA akışının iç araç ihtiyacıyla birleştirir.

    Profilin ``max_tool_calls=0`` tercihi WEB araçları içindir; yerel bölüm
    araması akışın mekanik parçasıdır ve ``max_retrieval_attempts + 1``
    (indeksleme) ile sınırlı ayrılmıştır. Model/token/süre sınırları profili
    aynen uygular.
    """
    return BudgetPolicy.from_budget_profile(
        profile,
        max_tool_attempts=max(profile.max_tool_calls, config.max_retrieval_attempts + 1),
    )


def build_article_qa_graph(deps: QaDeps):
    """Node'ları ve koşullu geçişleri kurar; derlenmiş graph döndürür."""
    graph: StateGraph = StateGraph(QaState)
    graph.add_node("validate", make_validate(deps))
    graph.add_node("retrieve", make_retrieve(deps))
    graph.add_node("evaluate", make_evaluate(deps))
    graph.add_node("generate", make_generate(deps))
    graph.add_node("control", make_control(deps))
    graph.add_node("finalize", make_finalize(deps))

    graph.add_edge(START, "validate")
    graph.add_edge("validate", "retrieve")
    graph.add_edge("retrieve", "evaluate")
    graph.add_conditional_edges("evaluate", after_evaluate, ["generate", "retrieve", "finalize"])
    graph.add_edge("generate", "control")
    graph.add_edge("control", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def _terminal_outcome(deps: QaDeps, state: QaState, error: PortError, elapsed: float) -> AgentOutcome:
    """Port hatasını terminal ``AgentOutcome``'a çevirir (plan durum ayrımı)."""
    usage = usage_record_from_events(
        deps.context.run_id, list(state.get("usage_events") or []), duration_seconds=elapsed
    )
    if error.code is AgentErrorCode.CANCELLED:
        return AgentOutcome(
            selected_mode=deps.mode,
            status=RunStatus.CANCELLED,
            source_scope=SourceScope.ARTICLE,
            usage=usage,
            error_code=None,
            error_message=error.message,
        )
    return AgentOutcome(
        selected_mode=deps.mode,
        status=RunStatus.FAILED,
        source_scope=SourceScope.ARTICLE,
        usage=usage,
        error_code=error.code,
        error_message=error.message,
    )


async def run_article_qa(
    context: ExecutionContext,
    route: RouteDecision | None,
    *,
    model: Any,
    retriever: ArticleRetriever,
    content: Any | None = None,  # ContentRepository portu
    config: QaFlowConfig | None = None,
    policy: BudgetPolicy | None = None,
    store: BudgetStore | None = None,
    artifacts: ArtifactStore | None = None,
    cancel: CancellationToken | None = None,
    progress: ProgressSink | None = None,
) -> QaRunResult:
    """Makaleye bağlı soru-cevap graph'ını yürütür; terminal sonuç + state döner.

    Raises:
        PortError: yalnız depo arızası gibi terminal-olmayan yollarda; iş
            hataları terminal ``AgentOutcome``'a çevrilir.
    """
    flow_config = config or QaFlowConfig()
    budget_policy = policy or qa_policy_for(context.budget_profile, flow_config)
    budget_store = store or PolicyBudgetStore(budget_policy)
    artifact_store = artifacts or InMemoryArtifactStore()
    deadline = Deadline(budget_policy.max_duration_seconds)
    guard = BudgetGuard(budget_store, budget_policy, context.run_id)
    tasks = TaskContext(
        run_id=context.run_id, guard=guard, artifacts=artifact_store, cancel=cancel, deadline=deadline
    )
    deps = QaDeps(
        context=context,
        route=route,
        retriever=retriever,
        model=model,
        content=content,
        policy=budget_policy,
        guard=guard,
        tasks=tasks,
        config=flow_config,
        progress=progress,
        deadline=deadline,
    )

    initial: QaState = {
        "run_id": context.run_id,
        "context": context,
        "route": route,
        "retrieval_query": build_retrieval_entry_query(
            context, max_history_tokens=flow_config.max_history_query_tokens
        ),
        "retrieval_attempt": 1,
        "rewritten": False,
        "retrieved": [],
        "citations": [],
        "sections": [],
        "usage_events": [],
        "errors": [],
    }
    app = build_article_qa_graph(deps)
    try:
        final_state: QaState = await app.ainvoke(initial)
        outcome = final_state.get("outcome")
        if outcome is None:  # pragma: no cover - graph tüm yolları outcome'a bağlar
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR, "QA graph terminal sonuç üretmedi", port="qa.runner"
            )
    except PortError as error:
        final_state = dict(initial)
        final_state["usage_events"] = guard.recorded_events
        outcome = _terminal_outcome(deps, final_state, error, deadline.elapsed())
    except asyncio.CancelledError:
        final_state = dict(initial)
        final_state["usage_events"] = guard.recorded_events
        outcome = _terminal_outcome(
            deps,
            final_state,
            PortError(AgentErrorCode.CANCELLED, "yürütüm iptal edildi", port="qa.runner"),
            deadline.elapsed(),
        )

    sections = list(final_state.get("sections") or [])
    return QaRunResult(outcome=outcome, state=final_state, sections=sections)
