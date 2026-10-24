"""Analysis alt akışının graph yürütücüsü (plan A5).

Graph şekli plan A5'in analysis adımlarını izler ve kanıt koşullu kenarla
üretime bağlanır [LG-RAG#C1]:

    START → plan → validate → gather → evidence ─┬─ (kanıt var) ─→ generate → control → finalize → END
                                                 └─ (kanıt yok) ─→ finalize

``validate`` düğümü A4 QA akışınınkini yeniden kullanır (bağlam doğrulama
tek sözleşmedir). Web erişimi yoktur: bağımlılık kümesinde web portu
bulunmaz (plan A4/A5; web A6 kapsamıdır).

Terminal eşleme A4 ile aynıdır: ``CANCELLED`` → ``cancelled``; diğer
``PortError`` kodları → ``failed``. Bütçe profili, mod farkının bütçe
karşılığı olarak analysis adımlarını karşılayacak araç üst sınırıyla
kurulur ve sunucu profilini asla aşmaz.
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
from ..models import AgentOutcome, ExecutionContext, ModeUpgradeRecord, RouteDecision, RunStatus, SourceScope
from ..ports import BudgetStore, CancellationToken, ProgressSink
from ..qa.models import QaFlowConfig
from ..qa.nodes import make_validate
from ..qa.runner import QaDeps
from ..state.artifacts import ArtifactStore, InMemoryArtifactStore
from ..state.events import usage_record_from_events
from .models import AnalysisConfig, AnalysisRunResult
from .nodes import (
    AnalysisDeps,
    after_evidence,
    make_control,
    make_evidence,
    make_finalize,
    make_gather,
    make_generate,
    make_plan,
)
from .state import AnalysisState

__all__ = ["analysis_policy_for", "build_analysis_graph", "run_article_analysis"]


def analysis_policy_for(profile, config: AnalysisConfig) -> BudgetPolicy:
    """Bütçe profilini analysis akışının adım ihtiyacıyla birleştirir.

    Araç üst sınırı = 1 indeksleme + başlık başına arama + kapsam artırma
    turları için pay: ``max_headings * (1 + max_expansion_rounds) + 1``.
    Sunucu profilinin koyduğu sınır her zaman nihai üst sıradır.
    """
    needed = config.max_headings * (1 + config.max_expansion_rounds) + 1
    return BudgetPolicy.from_budget_profile(profile, max_tool_attempts=max(profile.max_tool_calls, needed))


def build_analysis_graph(deps: AnalysisDeps):
    """Node'ları ve koşullu geçişleri kurar; derlenmiş graph döndürür."""
    graph: StateGraph = StateGraph(AnalysisState)
    graph.add_node("plan", make_plan(deps))
    # Bağlam doğrulama A4 QA düğümüdür; AnalysisDeps aynı alan adlarını taşır.
    graph.add_node("validate", make_validate(_qa_deps_for_validate(deps)))
    graph.add_node("gather", make_gather(deps))
    graph.add_node("evidence", make_evidence(deps))
    graph.add_node("generate", make_generate(deps))
    graph.add_node("control", make_control(deps))
    graph.add_node("finalize", make_finalize(deps))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "validate")
    graph.add_edge("validate", "gather")
    graph.add_edge("gather", "evidence")
    graph.add_conditional_edges("evidence", after_evidence, ["generate", "finalize"])
    graph.add_edge("generate", "control")
    graph.add_edge("control", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def _qa_deps_for_validate(deps: AnalysisDeps) -> QaDeps:
    """``make_validate`` için QaDeps görünümü; yalnız validate'in okuduğu alanlar."""
    return QaDeps(
        context=deps.context,
        route=deps.route,
        retriever=deps.retriever,
        model=deps.model,
        content=deps.content,
        policy=deps.policy,
        guard=deps.guard,
        tasks=deps.tasks,
        config=QaFlowConfig(),
        progress=deps.progress,
        deadline=deps.deadline,
    )


def _terminal_outcome(deps: AnalysisDeps, state: AnalysisState, error: PortError, elapsed: float) -> AgentOutcome:
    """Port hatasını terminal ``AgentOutcome``'a çevirir (A4 durum ayrımı)."""
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


async def run_article_analysis(
    context: ExecutionContext,
    route: RouteDecision | None,
    *,
    model: Any,
    retriever: ArticleRetriever,
    content: Any | None = None,
    config: AnalysisConfig | None = None,
    policy: BudgetPolicy | None = None,
    store: BudgetStore | None = None,
    artifacts: ArtifactStore | None = None,
    mode_upgrade: ModeUpgradeRecord | None = None,
    cancel: CancellationToken | None = None,
    progress: ProgressSink | None = None,
) -> AnalysisRunResult:
    """Analysis graph'ını yürütür; terminal sonuç + state döner.

    ``mode_upgrade`` verilirse graph state'ine yazılır ve terminal
    ``AgentOutcome.mode_upgrades`` ile taşınır (plan A5: kayıtlı mod
    yükseltmesi). Yükseltme çağıran tarafça sınırlanır: çalışma başına en
    fazla bir kayıt, yalnız fast → analysis (``ModeUpgradeRecord`` doğrulayıcı).

    Raises:
        PortError: yalnız depo arızası gibi terminal-olmayan yollarda; iş
            hataları terminal ``AgentOutcome``'a çevrilir.
    """
    flow_config = config or AnalysisConfig()
    budget_policy = policy or analysis_policy_for(context.budget_profile, flow_config)
    budget_store = store or PolicyBudgetStore(budget_policy)
    artifact_store = artifacts or InMemoryArtifactStore()
    deadline = Deadline(budget_policy.max_duration_seconds)
    guard = BudgetGuard(budget_store, budget_policy, context.run_id)
    tasks = TaskContext(
        run_id=context.run_id, guard=guard, artifacts=artifact_store, cancel=cancel, deadline=deadline
    )
    deps = AnalysisDeps(
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

    initial: AnalysisState = {
        "run_id": context.run_id,
        "context": context,
        "route": route,
        "retrieved": [],
        "scope_expanded": False,
        "citations": [],
        "sections": [],
        "mode_upgrade": mode_upgrade,
        "usage_events": [],
        "errors": [],
    }
    app = build_analysis_graph(deps)
    try:
        final_state: AnalysisState = await app.ainvoke(initial)
        outcome = final_state.get("outcome")
        if outcome is None:  # pragma: no cover - graph tüm yolları outcome'a bağlar
            raise PortError(
                AgentErrorCode.PROVIDER_ERROR, "analysis graph terminal sonuç üretmedi", port="analysis.runner"
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
            PortError(AgentErrorCode.CANCELLED, "yürütüm iptal edildi", port="analysis.runner"),
            deadline.elapsed(),
        )

    sections = list(final_state.get("sections") or [])
    return AnalysisRunResult(outcome=outcome, state=final_state, sections=sections)
