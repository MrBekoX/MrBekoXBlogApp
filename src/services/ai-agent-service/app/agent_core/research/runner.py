"""Derin araştırma graph yürütücüsü (plan A7).

Graph şekli plan A7'nin adım akışını izler; ikinci tur koşullu ``Send``
kenarıyla döner [LG-WORKFLOWS#C2]:

    START → validate → extract → plan ─┬─ (görev var) ─→ gather_worker* → evaluate → coverage ─┐
                                       │                                                      ├─ (görev var) → gather_worker*
                                       └─ (görev yok) ─────────────────────────→ compare → report → control → finalize → END

``gather_worker`` ``Send`` ile alt soru/iddia başına paralel açılır; paralel
worker'lar ortak bütçeyi ``BudgetGuard``'ın atomik rezervasyonuyla paylaşır
(plan A7). Terminal eşleme A4/A5 ile aynıdır: ``CANCELLED`` → ``cancelled``;
beklenmeyen ``PortError`` → ``failed``. Bütçe/süre bitimi node içinde
yakalanıp ``partial`` yoluna bağlanır: bulgusu olan derin araştırma
yanıtsız kalmaktan iyidir (mekanik kısmi rapor).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
from .models import ResearchFlowConfig, ResearchReport
from .nodes import (
    ResearchDeps,
    after_coverage,
    dispatch_gather,
    make_compare,
    make_control,
    make_coverage,
    make_evaluate,
    make_extract,
    make_finalize,
    make_gather_worker,
    make_plan,
    make_report,
    make_validate,
)
from .state import ResearchState

__all__ = ["ResearchRunResult", "build_deep_research_graph", "research_policy_for", "run_deep_research"]


def research_policy_for(profile, config: ResearchFlowConfig) -> BudgetPolicy:
    """Bütçe profilini araştırma akışının ihtiyacıyla birleştirir.

    Araç üst sınırı sunucu profiliyle başlar; arama/kaynak sayfası türleri
    ``BudgetStore`` kendi tür sınırlarıyla denetlenir (politika
    ``max_search_calls`` / ``max_source_pages``). Profilin koyduğu sınır
    her zaman nihai üst sıradır.
    """
    return BudgetPolicy.from_budget_profile(
        profile,
        max_tool_attempts=max(profile.max_tool_calls, 1),
    )


@dataclass
class ResearchRunResult:
    """Bir araştırma graph yürütmesinin çıktısı; A4 ``QaRunResult`` biçimi."""

    outcome: AgentOutcome
    state: dict
    report: ResearchReport | None = field(default=None)


def build_deep_research_graph(deps: ResearchDeps):
    """Node'ları ve koşullu geçişleri kurar; derlenmiş graph döndürür."""
    graph: StateGraph = StateGraph(ResearchState)
    graph.add_node("validate", make_validate(deps))
    graph.add_node("extract", make_extract(deps))
    graph.add_node("plan", make_plan(deps))
    graph.add_node("gather_worker", make_gather_worker(deps))
    graph.add_node("evaluate", make_evaluate(deps))
    graph.add_node("coverage", make_coverage(deps))
    graph.add_node("compare", make_compare(deps))
    graph.add_node("report", make_report(deps))
    graph.add_node("control", make_control(deps))
    graph.add_node("finalize", make_finalize(deps))

    graph.add_edge(START, "validate")
    graph.add_edge("validate", "extract")
    graph.add_edge("extract", "plan")
    graph.add_conditional_edges("plan", dispatch_gather, ["gather_worker", "compare"])
    graph.add_edge("gather_worker", "evaluate")
    graph.add_edge("evaluate", "coverage")
    graph.add_conditional_edges("coverage", after_coverage, ["gather_worker", "compare"])
    graph.add_edge("compare", "report")
    graph.add_edge("report", "control")
    graph.add_edge("control", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def _terminal_outcome(deps: ResearchDeps, state: dict, error: PortError, elapsed: float) -> AgentOutcome:
    """Port hatasını terminal ``AgentOutcome``'a çevirir (plan durum ayrımı)."""
    usage = usage_record_from_events(
        deps.context.run_id, list(state.get("usage_events") or []), duration_seconds=elapsed
    )
    if error.code is AgentErrorCode.CANCELLED:
        return AgentOutcome(
            selected_mode=deps.mode,
            status=RunStatus.CANCELLED,
            source_scope=SourceScope.ARTICLE_AND_WEB,
            usage=usage,
            error_code=None,
            error_message=error.message,
        )
    return AgentOutcome(
        selected_mode=deps.mode,
        status=RunStatus.FAILED,
        source_scope=SourceScope.ARTICLE_AND_WEB,
        usage=usage,
        error_code=error.code,
        error_message=error.message,
    )


async def run_deep_research(
    context: ExecutionContext,
    route: RouteDecision | None,
    *,
    model: Any,  # noqa: ANN401 - ModelProvider portu (döngüsel import istenmedi)
    web_tools: dict[str, Any],
    content: Any | None = None,  # ContentRepository portu (K7)
    config: ResearchFlowConfig | None = None,
    policy: BudgetPolicy | None = None,
    store: BudgetStore | None = None,
    artifacts: ArtifactStore | None = None,
    cancel: CancellationToken | None = None,
    progress: ProgressSink | None = None,
) -> ResearchRunResult:
    """Makale merkezli derin araştırma graph'ını yürütür; terminal sonuç + rapor döner.

    ``web_tools`` A6 ``build_web_tools`` çıktısıdır; ``search_web`` aracı yoksa
    graph ``config_error`` ile başarısız olur (anlaşılır yapılandırma hatası).

    Raises:
        PortError: yalnız depo arızası gibi terminal-olmayan yollarda; iş
            hataları terminal ``AgentOutcome``'a çevrilir.
    """
    flow_config = config or ResearchFlowConfig()
    budget_policy = policy or research_policy_for(context.budget_profile, flow_config)
    budget_store = store or PolicyBudgetStore(budget_policy)
    artifact_store = artifacts or InMemoryArtifactStore()
    deadline = Deadline(budget_policy.max_duration_seconds)
    guard = BudgetGuard(budget_store, budget_policy, context.run_id)
    tasks = TaskContext(
        run_id=context.run_id, guard=guard, artifacts=artifact_store, cancel=cancel, deadline=deadline
    )
    deps = ResearchDeps(
        context=context,
        route=route,
        model=model,
        tools=web_tools,
        content=content,
        policy=budget_policy,
        guard=guard,
        tasks=tasks,
        config=flow_config,
        progress=progress,
        deadline=deadline,
    )

    initial: ResearchState = {
        "run_id": context.run_id,
        "context": context,
        "route": route,
        "research_round": 0,
        "claims": [],
        "sources": [],
        "evidence": [],
        "comparison": [],
        "findings": [],
        "usage_events": [],
        "errors": [],
        "artifact_refs": [],
    }
    app = build_deep_research_graph(deps)
    try:
        final_state: ResearchState = await app.ainvoke(initial)
        outcome = final_state.get("outcome")
        if outcome is None:  # pragma: no cover - graph tüm yolları outcome'a bağlar
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR,
                "derin araştırma graph'ı terminal sonuç üretmedi",
                port="research.runner",
            )
    except PortError as error:
        final_state = dict(initial)
        outcome = _terminal_outcome(deps, final_state, error, deadline.elapsed())
    except asyncio.CancelledError:
        final_state = dict(initial)
        outcome = _terminal_outcome(
            deps,
            final_state,
            PortError(AgentErrorCode.CANCELLED, "yürütüm iptal edildi", port="research.runner"),
            deadline.elapsed(),
        )

    report = final_state.get("report")
    return ResearchRunResult(outcome=outcome, state=dict(final_state), report=report)
