"""Ölçüm koşucusu: küme örneklerini gerçek giriş noktaları üzerinden çalıştırır.

Her örnek; ``agent_core.entrypoints`` (prepare_and_route / execute_plan /
resume) ve üretim akışları (qa/analysis/research/guidance/collab) ÜZERİNDEN
koşar — davranış hiçbir yerden taklit edilmez. Tüm model/embedding/arama
erişimi ``evals.providers`` double'larıdır: koşu ``provider="test_executor"``
işaretli sonuç üretir ve gerçek sağlayıcı başarısı SAYILMAZ.

Ölçülen metrik aileleri (plan A10):
1. Görev ve mod kararlarının doğruluğu (rota + terminal etkin mod).
2. İlgili bölümün bulunması (doğrudan retrieval sonda + atıf hedefi).
3. İddia–kanıt desteği ve hatalı kaynak oranı (atıf→bölüm örtüşmesi).
4. Fast/analysis gecikmesi (test sağlayıcıyla orkestrasyon yükü; yapay
   gecikmeli deadline senaryosu bu metrikten hariçtir).
5. Araştırma başına araç/model kullanımı ve bütçe profili uyumu.
6. Checkpoint'ten devam başarısı (resume senaryoları).
7. Bütçe/iptal davranışı (terminal doğruluğu).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agent_core.analysis.models import AnalysisConfig
from agent_core.budget.guard import BudgetGuard
from agent_core.budget.policy import BudgetPolicy
from agent_core.budget.store import PolicyBudgetStore
from agent_core.checkpoint.models import new_execution_id
from agent_core.checkpoint.resume import load_resume_payload
from agent_core.checkpoint.store import FileCheckpointStore
from agent_core.collab.models import CollabResumeInput
from agent_core.content import chunk_article
from agent_core.content.config import ChunkingConfig, EmbeddingModelConfig
from agent_core.content.models import IndexedChunk
from agent_core.entrypoints import ResumeRequest, execute_plan, prepare_and_route, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.guidance.models import ArticleCatalogEntry
from agent_core.models import (
    ArticleSnapshot,
    BudgetProfile,
    ExecutionContext,
    ValidatedActionResult,
    compute_content_hash,
)
from agent_core.ports import ProfileSummary, ProjectRecord
from agent_core.qa.models import QaFlowConfig
from agent_core.qa.nodes import build_retrieval_entry_query
from agent_core.qa.retrieval import SnapshotRetriever
from agent_core.research.models import ResearchFlowConfig
from agent_core.research.runner import research_policy_for
from agent_core.web.settings import WebToolSettings
from agent_core.web.tools import build_web_tools

from . import articles as fx
from .cache_policy import (
    answer_cache_key,
    config_fingerprint,
    is_shared_cache_eligible,
    question_scope,
)
from .dataset import EvalCase, cases_for_suite
from .metrics import audit_citations, citations_hit_section, within_budget_profile
from .providers import (
    TEST_PROVIDER_ID,
    EvalEmbeddingProvider,
    GroundedTestModel,
    LocalPageServer,
    PreCancelledToken,
    RecordingProgressSink,
    ScriptedRouterModel,
    ScriptedSearchProvider,
    SlowTestModel,
    StubCancellationToken,
)

__all__ = ["CaseResult", "EvalRuntime", "run_cases"]

EMBEDDING_MODEL_ID = "eval-embedding-v1"
EMBEDDING_DIMENSIONS = 64


def _embedding_config() -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        model_id=EMBEDDING_MODEL_ID,
        dimensions=EMBEDDING_DIMENSIONS,
        max_chunk_tokens=256,
        chars_per_token=4,
    )


@dataclass
class CheckResult:
    """Tek beklenti denetimi."""

    name: str
    expected: Any
    actual: Any
    ok: bool

    def as_dict(self) -> dict:
        return {"name": self.name, "expected": self.expected, "actual": self.actual, "ok": self.ok}


@dataclass
class CaseResult:
    """Bir örneğin ölçüm kaydı; sağlayıcı işaretlemesi taşır."""

    case_id: str
    suite: str
    areas: list[str]
    kind: str
    title: str
    provider: str = TEST_PROVIDER_ID
    ok: bool = True
    duration_s: float = 0.0
    latency_family: str | None = None
    latency_artificial: bool = False
    route: dict | None = None
    terminal: dict | None = None
    usage: dict | None = None
    audit: dict | None = None
    section_probe_hit: bool | None = None
    section_cited: bool | None = None
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "suite": self.suite,
            "areas": self.areas,
            "kind": self.kind,
            "title": self.title,
            "provider": self.provider,
            "ok": self.ok,
            "duration_s": round(self.duration_s, 4),
            "latency_family": self.latency_family,
            "latency_artificial": self.latency_artificial,
            "route": self.route,
            "terminal": self.terminal,
            "usage": self.usage,
            "audit": self.audit,
            "section_probe_hit": self.section_probe_hit,
            "section_cited": self.section_cited,
            "checks": [check.as_dict() for check in self.checks],
            "error": self.error,
        }


def _budget_profile(case: EvalCase) -> BudgetProfile:
    base = dict(
        max_model_calls=4,
        max_total_tokens=120_000,
        max_tool_calls=24,
        max_web_search_calls=8,
        max_duration_seconds=60.0,
    )
    if case.budget_profile != "eval-research":
        base = dict(
            max_model_calls=2,
            max_total_tokens=8000,
            max_tool_calls=0,
            max_web_search_calls=0,
            max_duration_seconds=60.0,
        )
    base.update(case.budget_overrides)
    return BudgetProfile(name=case.budget_profile, **base)


def _make_context(case: EvalCase, run_id: str, snapshot: ArticleSnapshot | None) -> ExecutionContext:
    from agent_core.models import ConversationTurn

    history = [
        ConversationTurn(role=turn["role"], content=turn["content"], created_at=fx.NOW)
        for turn in case.conversation_history
    ]
    defaults: dict[str, Any] = dict(
        run_id=run_id,
        conversation_id=f"conv-{run_id}",
        question=case.question,
        language=case.language,
        mode_preference=case.mode_preference,
        selected_text=case.selected_text,
        conversation_history=history,
        budget_profile=_budget_profile(case),
    )
    if snapshot is not None:
        defaults.update(
            article_id=snapshot.article_id,
            article_revision=snapshot.article_revision,
            article_content_hash=snapshot.content_hash,
            article_snapshot=snapshot,
        )
    return ExecutionContext(**defaults)


def _make_retriever(snapshot: ArticleSnapshot) -> SnapshotRetriever:
    retriever = SnapshotRetriever(
        embedding_provider=EvalEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS),
        model_config=_embedding_config(),
        canonical_url_template=fx.URL_TEMPLATE,
    )
    import asyncio

    asyncio.run(retriever.ensure_indexed(snapshot))
    return retriever


async def _build_retriever_async(snapshot: ArticleSnapshot) -> SnapshotRetriever:
    """Çalışan olay döngüsü içinden retriever kurar (senaryo yolları)."""
    retriever = SnapshotRetriever(
        embedding_provider=EvalEmbeddingProvider(dimensions=EMBEDDING_DIMENSIONS),
        model_config=_embedding_config(),
        canonical_url_template=fx.URL_TEMPLATE,
    )
    await retriever.ensure_indexed(snapshot)
    return retriever


def _chunk_maps(snapshot: ArticleSnapshot) -> tuple[dict[int, str], dict[int, str]]:
    """chunk_index → (içerik, başlık yolu) haritaları; atıf denetimi içindir."""
    prepared = chunk_article(snapshot, ChunkingConfig.for_model(_embedding_config()))
    contents: dict[int, str] = {}
    headings: dict[int, str] = {}
    for item in prepared:
        contents[item.chunk.chunk_index] = item.chunk.content
        headings[item.chunk.chunk_index] = " > ".join(item.heading_path)
    return contents, headings


def _route_dict(route) -> dict:
    return {
        "selected_mode": route.selected_mode.value,
        "intent": route.intent.value,
        "needs_web": route.needs_web,
        "needs_clarification": route.needs_clarification,
        "source_scope": route.source_scope.value if route.source_scope is not None else None,
    }


def _outcome_dict(outcome) -> dict:
    return {
        "status": outcome.status.value,
        "mode": outcome.selected_mode.value,
        "error_code": outcome.error_code.value if outcome.error_code is not None else None,
        "answer_chars": len(outcome.answer or ""),
        "report_chars": len(outcome.report or ""),
        "citation_count": len(outcome.citations),
        "web_citation_count": sum(1 for c in outcome.citations if c.kind == "web"),
        "unresolved_count": len(outcome.unresolved_questions),
        "model_calls": outcome.usage.model_calls,
        "tool_calls": outcome.usage.tool_calls,
        "web_search_calls": outcome.usage.web_search_calls,
    }


class EvalRuntime:
    """Koşu ortamı: yerel sayfa sunucusu + checkpoint dizini yönetimi."""

    def __init__(self) -> None:
        self._pages: LocalPageServer | None = None
        self._tmp: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> "EvalRuntime":
        self._tmp = tempfile.TemporaryDirectory(prefix="evals-a10-")
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._pages is not None:
            self._pages.__exit__(*exc)
            self._pages = None
        if self._tmp is not None:
            shutil.rmtree(self._tmp.name, ignore_errors=True)
            self._tmp = None

    @property
    def page_base_url(self) -> str:
        if self._pages is None:
            self._pages = LocalPageServer(fx.LOCAL_PAGES)
            self._pages.__enter__()
        return self._pages.base_url

    def checkpoint_store(self, label: str) -> FileCheckpointStore:
        import os

        base = os.path.join(self._tmp.name if self._tmp else tempfile.gettempdir(), label)
        os.makedirs(base, exist_ok=True)
        return FileCheckpointStore(base)


def _fresh_checkpoint_dir(runtime: EvalRuntime, case_id: str) -> FileCheckpointStore:
    return runtime.checkpoint_store(f"ckpt-{case_id}")


def _check(name: str, expected: Any, actual: Any) -> CheckResult:
    return CheckResult(name=name, expected=expected, actual=actual, ok=(expected == actual))


def _contains_check(name: str, needles: list[str], haystack: str) -> list[CheckResult]:
    folded = (haystack or "").casefold()
    return [
        CheckResult(f"{name}:{needle[:40]}", needle, needle.casefold() in folded, needle.casefold() in folded)
        for needle in needles
    ]


def _excludes_check(name: str, forbidden: list[str], haystack: str) -> list[CheckResult]:
    folded = (haystack or "").casefold()
    return [
        CheckResult(
            f"{name}:{needle[:40]}", f"yok[{needle[:40]}]",
            needle.casefold() not in folded, needle.casefold() not in folded,
        )
        for needle in forbidden
    ]


# --- rota örnekleri -----------------------------------------------------------


def _run_route_case(case: EvalCase, runtime: EvalRuntime) -> CaseResult:
    result = CaseResult(
        case_id=case.case_id, suite=case.suite, areas=case.areas, kind=case.kind, title=case.title
    )
    snapshot = fx.EVAL_ARTICLES.get(case.article_id) if case.article_id else None
    context = _make_context(case, f"eval-{case.case_id}", snapshot)
    router = (
        ScriptedRouterModel(case.router_suggestions) if case.use_router_model else None
    )
    import asyncio

    started = time.monotonic()
    prepared = asyncio.run(prepare_and_route(context, router_model=router))
    result.duration_s = time.monotonic() - started
    result.route = _route_dict(prepared.route)
    route = prepared.route
    if case.expected.mode is not None:
        result.checks.append(_check("mode", case.expected.mode, route.selected_mode.value))
    if case.expected.intent is not None:
        result.checks.append(_check("intent", case.expected.intent, route.intent.value))
    if case.expected.needs_web is not None:
        result.checks.append(_check("needs_web", case.expected.needs_web, route.needs_web))
    if case.expected.needs_clarification is not None:
        result.checks.append(
            _check(
                "needs_clarification",
                case.expected.needs_clarification,
                route.needs_clarification,
            )
        )
    if case.expected.source_scope is not None:
        result.checks.append(
            _check(
                "source_scope",
                case.expected.source_scope,
                route.source_scope.value if route.source_scope else None,
            )
        )
    result.ok = all(check.ok for check in result.checks)
    return result


# --- yürütme örnekleri ---------------------------------------------------------


def _execute_wiring(case: EvalCase, context: ExecutionContext, runtime: EvalRuntime):
    """Ortak yürütme kablolaması: model, rehberlik kaynakları, web.

    Retriever burada KURULMAZ: bu işlev hem senkron hem olay-döngüsü içinden
    çağrılabilir; retriever kurulumu çağıranın bağlamına göre (``_make_retriever``
    / ``_build_retriever_async``) yapılır.
    """
    model = GroundedTestModel()
    profile_repo = _ProfileRepo()
    project_repo = _ProjectRepo()
    catalog = _catalog()
    budget = None
    web_tools = None
    if case.web_wired:
        policy = research_policy_for(context.budget_profile, ResearchFlowConfig())
        store = PolicyBudgetStore(policy)
        guard = BudgetGuard(store, policy, context.run_id)
        settings = WebToolSettings(
            environment="test",
            allow_loopback=True,
            allowed_ports=(int(runtime.page_base_url.rsplit(":", 1)[-1]),),
            connect_timeout_s=2.0,
            header_timeout_s=2.0,
            body_idle_timeout_s=3.0,
            resolver_timeout_s=2.0,
            total_timeout_s=6.0,
            retry_backoff_base_s=0.0,
        )
        search = ScriptedSearchProvider(runtime.page_base_url, fx.SEARCH_INDEX)
        web_tools = build_web_tools(guard, settings, search_provider=search)
        budget = store
    return model, None, budget, web_tools, profile_repo, project_repo, catalog


class _ProfileRepo:
    is_test_double = True

    async def get_profile(self) -> ProfileSummary:
        return ProfileSummary(
            name=fx.PROFILE_SUMMARY["name"],
            job_title=fx.PROFILE_SUMMARY["job_title"],
            description=fx.PROFILE_SUMMARY["description"],
            links=fx.PROFILE_SUMMARY["links"],
            skills=fx.PROFILE_SUMMARY["skills"],
            updated_at=fx.NOW,
        )


class _ProjectRepo:
    is_test_double = True

    async def list_projects(self) -> list[ProjectRecord]:
        return [
            ProjectRecord(
                name=item["name"],
                description=item["description"],
                technologies=item["technologies"],
                links=item["links"],
            )
            for item in fx.PROJECT_RECORDS
        ]


def _catalog() -> list[ArticleCatalogEntry]:
    return [
        ArticleCatalogEntry(
            article_id=item["article_id"],
            title=item["title"],
            url=item["url"],
            topics=item["topics"],
            summary=item["summary"],
        )
        for item in fx.ARTICLE_CATALOG
    ]


def _section_probe(case: EvalCase, context: ExecutionContext, retriever) -> bool | None:
    """İlgili bölümün bulunması: doğrudan retrieval sonda (plan metriği 2)."""
    if case.expected.expected_section is None or retriever is None:
        return None
    import asyncio

    query = build_retrieval_entry_query(context)
    records = asyncio.run(
        retriever.retrieve(
            query,
            article_id=context.article_id or "",
            article_revision=context.article_revision or 0,
            top_k=4,
        )
    )
    expected = case.expected.expected_section.casefold()
    for record in records:
        heading = " > ".join(record.heading_path).casefold()
        if expected in heading:
            return True
    return False


def _run_execute_case(case: EvalCase, runtime: EvalRuntime) -> CaseResult:
    import asyncio

    result = CaseResult(
        case_id=case.case_id, suite=case.suite, areas=case.areas, kind=case.kind, title=case.title
    )
    snapshot = fx.EVAL_ARTICLES.get(case.article_id) if case.article_id else None
    context = _make_context(case, f"eval-{case.case_id}", snapshot)
    model, retriever, budget, web_tools, profile_repo, project_repo, catalog = _execute_wiring(
        case, context, runtime
    )
    if retriever is None and context.article_snapshot is not None:
        retriever = _make_retriever(context.article_snapshot)
    progress = RecordingProgressSink()

    async def _flow():
        prepared = await prepare_and_route(context)
        result.route = _route_dict(prepared.route)
        started = time.monotonic()
        outcome = await execute_plan(
            prepared,
            model=model,
            retriever=retriever,
            budget=budget,
            web_tools=web_tools,
            profile_repository=profile_repo,
            project_repository=project_repo,
            article_catalog=catalog if case.case_id != "g05" else None,
            progress=progress,
        )
        committed_view = None
        if budget is not None:
            usage_view = await budget.usage(context.run_id)
            committed_view = {
                kind.value if hasattr(kind, "value") else str(kind): count
                for kind, count in usage_view.committed.items()
            }
        return outcome, time.monotonic() - started, committed_view

    try:
        outcome, elapsed, committed_view = asyncio.run(_flow())
    except PortError as error:  # rehberlik reddi gibi yükselen davranışlar
        result.error = f"{error.code.value}: {error.message}"
        result.checks.append(
            _check("raised", case.expected.raises_error_code, error.code.value)
            if case.expected.raises_error_code is not None
            else CheckResult("unexpected_raise", None, error.code.value, False)
        )
        result.ok = all(check.ok for check in result.checks)
        return result

    result.duration_s = elapsed
    result.latency_family = outcome.selected_mode.value
    result.terminal = _outcome_dict(outcome)
    result.usage = {
        "model_calls": outcome.usage.model_calls,
        "tool_calls": outcome.usage.tool_calls,
        "web_search_calls": outcome.usage.web_search_calls,
        "total_tokens": outcome.usage.total_tokens,
        "budget_committed": committed_view or {},
    }

    # Rota beklentileri (varsa) hazırlık kararı üzerinden ölçülür.
    route = result.route or {}
    if case.expected.mode is not None and case.expected.expected_section is None and case.kind == "route":
        result.checks.append(_check("mode", case.expected.mode, route.get("selected_mode")))
    if case.expected.intent is not None:
        result.checks.append(_check("intent", case.expected.intent, route.get("intent")))
    if case.expected.needs_web is not None:
        result.checks.append(_check("needs_web", case.expected.needs_web, route.get("needs_web")))
    if case.expected.needs_clarification is not None:
        result.checks.append(
            _check(
                "needs_clarification",
                case.expected.needs_clarification,
                route.get("needs_clarification"),
            )
        )
    if case.expected.source_scope is not None:
        result.checks.append(
            _check("source_scope", case.expected.source_scope, route.get("source_scope"))
        )
    if case.expected.mode is not None and case.kind == "execute":
        result.checks.append(_check("mode", case.expected.mode, outcome.selected_mode.value))

    # Terminal beklentileri.
    if case.expected.status is not None:
        result.checks.append(_check("status", case.expected.status, outcome.status.value))
    if case.expected.status_in:
        actual = outcome.status.value
        result.checks.append(
            CheckResult("status_in", case.expected.status_in, actual, actual in case.expected.status_in)
        )
    if case.expected.error_code is not None:
        actual = outcome.error_code.value if outcome.error_code is not None else None
        result.checks.append(_check("error_code", case.expected.error_code, actual))

    text = outcome.answer or outcome.report or ""
    result.checks.extend(_contains_check("answer", case.expected.answer_contains, text))
    result.checks.extend(_contains_check("report", case.expected.report_contains, outcome.report or ""))
    result.checks.extend(_excludes_check("answer", case.expected.answer_excludes, text))
    if case.expected.min_unresolved is not None:
        count = len(outcome.unresolved_questions)
        ok = count >= case.expected.min_unresolved
        result.checks.append(
            CheckResult("min_unresolved", f">={case.expected.min_unresolved}", count, ok)
        )

    # Atıf denetimi (metrik 3): iddia–kanıt desteği + hatalı kaynak oranı.
    if snapshot is not None and outcome.citations:
        contents, headings = _chunk_maps(snapshot)
        audit = audit_citations(outcome.answer or outcome.report or "", outcome.citations, contents)
        result.audit = {
            "total": audit.total,
            "supported": audit.supported,
            "unsupported": audit.unsupported,
            "support_rate": round(audit.support_rate, 4),
            "wrong_source_rate": round(audit.wrong_source_rate, 4),
        }
        if case.expected.min_citations is not None:
            ok = audit.total >= case.expected.min_citations
            result.checks.append(CheckResult("min_citations", f">={case.expected.min_citations}", audit.total, ok))
        if case.expected.zero_citations:
            result.checks.append(_check("zero_citations", 0, audit.total))
        if case.expected.min_web_citations is not None:
            web_count = sum(1 for c in outcome.citations if c.kind == "web")
            ok = web_count >= case.expected.min_web_citations
            result.checks.append(
                CheckResult("min_web_citations", f">={case.expected.min_web_citations}", web_count, ok)
            )
        if case.expected.expected_section is not None:
            from .metrics import citations_hit_section

            cited = citations_hit_section(outcome.citations, headings, case.expected.expected_section)
            result.section_cited = cited
            result.checks.append(CheckResult("expected_section_cited", case.expected.expected_section, cited, cited))
    elif case.expected.min_citations is not None or case.expected.zero_citations:
        total = len(outcome.citations)
        result.audit = {"total": total, "supported": 0, "unsupported": [], "support_rate": 0.0, "wrong_source_rate": 0.0}
        if case.expected.min_citations is not None:
            ok = total >= case.expected.min_citations
            result.checks.append(CheckResult("min_citations", f">={case.expected.min_citations}", total, ok))
        if case.expected.zero_citations:
            result.checks.append(_check("zero_citations", 0, total))

    # Doğrudan retrieval sonda (metrik 2).
    result.section_probe_hit = _section_probe(case, context, retriever) if case.expected.expected_section else None
    if case.expected.expected_section is not None and result.section_probe_hit is not None:
        result.checks.append(
            CheckResult("expected_section_found", case.expected.expected_section, result.section_probe_hit, result.section_probe_hit)
        )

    # Kullanım sınırları (metrik 5).
    if case.expected.model_calls_zero:
        result.checks.append(_check("model_calls_zero", 0, outcome.usage.model_calls))
    if case.expected.min_model_calls is not None:
        ok = outcome.usage.model_calls >= case.expected.min_model_calls
        result.checks.append(
            CheckResult("min_model_calls", f">={case.expected.min_model_calls}", outcome.usage.model_calls, ok)
        )
    if case.expected.max_model_calls is not None:
        ok = outcome.usage.model_calls <= case.expected.max_model_calls
        result.checks.append(
            CheckResult("max_model_calls", f"<={case.expected.max_model_calls}", outcome.usage.model_calls, ok)
        )
    if case.expected.min_tool_calls is not None:
        ok = outcome.usage.tool_calls >= case.expected.min_tool_calls
        result.checks.append(
            CheckResult("min_tool_calls", f">={case.expected.min_tool_calls}", outcome.usage.tool_calls, ok)
        )
    if case.expected.min_source_reads is not None:
        reads = (committed_view or {}).get("source_page_read", 0)
        ok = reads >= case.expected.min_source_reads
        result.checks.append(
            CheckResult("min_source_reads", f">={case.expected.min_source_reads}", reads, ok)
        )
    if case.expected.min_web_search_calls is not None:
        ok = outcome.usage.web_search_calls >= case.expected.min_web_search_calls
        result.checks.append(
            CheckResult(
                "min_web_search_calls", f">={case.expected.min_web_search_calls}", outcome.usage.web_search_calls, ok
            )
        )
    if case.expected.within_budget:
        in_budget, violations = within_budget_profile(outcome.usage, context.budget_profile)
        result.checks.append(CheckResult("within_budget", True, in_budget and not violations, in_budget and not violations))

    result.ok = all(check.ok for check in result.checks)
    return result


# --- resume/cache senaryoları --------------------------------------------------


def _collab_answers_input() -> CollabResumeInput:
    return CollabResumeInput(
        answers={
            "purpose": "Konuk yazı: asyncio serinize bir bölüm katmak istiyorum.",
            "scope": "Tek makale: kuyruk gözlemlenebilirliği üzerine uygulama rehberi.",
            "timeline": "Kasım ayı içinde ilk taslak.",
            "contact": "berkay@example.com",
        }
    )


def _run_resume_case(case: EvalCase, runtime: EvalRuntime) -> CaseResult:
    """Checkpoint/resume senaryoları; her senaryo kendi adımlarını kaydeder."""
    import asyncio

    result = CaseResult(
        case_id=case.case_id, suite=case.suite, areas=case.areas, kind=case.kind, title=case.title
    )
    snapshot = fx.EVAL_ARTICLES[case.article_id] if case.article_id else None
    scenario = case.scenario
    store = _fresh_checkpoint_dir(runtime, case.case_id)
    progress = RecordingProgressSink()
    profile_repo, project_repo, catalog = _ProfileRepo(), _ProjectRepo(), _catalog()

    async def _scenario():
        if scenario == "collab_first":
            return await _scenario_collab_first(case, runtime, store, progress)
        if scenario == "collab_answers":
            return await _scenario_collab_answers(case, runtime, store, progress, profile_repo, project_repo, catalog)
        if scenario == "collab_approval_unverified":
            return await _scenario_collab_approval(case, runtime, store, progress, profile_repo, project_repo, catalog, verified=False)
        if scenario == "collab_approval":
            return await _scenario_collab_approval(case, runtime, store, progress, profile_repo, project_repo, catalog, verified=True)
        if scenario == "resume_after_cancel":
            return await _scenario_resume_after_cancel(case, runtime, store, progress)
        if scenario == "resume_deadline":
            return await _scenario_resume_deadline(case, runtime, store)
        if scenario == "research_cancel":
            return await _scenario_research_cancel(case, runtime)
        if scenario == "resume_evidence_stale":
            return await _scenario_resume_stale(case, runtime, store, progress, stale=False)
        if scenario == "resume_not_resumable":
            return await _scenario_resume_stale(case, runtime, store, progress, stale=True)
        if scenario == "resume_wrong_execution":
            return await _scenario_resume_wrong_execution(case, runtime, store)
        raise ValueError(f"bilinmeyen senaryo: {scenario}")

    try:
        steps = asyncio.run(_scenario())
    except PortError as error:
        # Senaryo PortError'ı kendi içinde denetleyemediyse beklenti dışıdır.
        result.error = f"{error.code.value}: {error.message}"
        result.checks.append(CheckResult("unexpected_raise", None, error.code.value, False))
        result.ok = False
        return result

    result.checks.extend(steps)
    result.route = _scenario_state.get("route_dict")
    result.terminal = _scenario_state.get("terminal")
    result.usage = _scenario_state.get("usage")
    result.duration_s = _scenario_state.get("elapsed", 0.0)
    result.latency_family = _scenario_state.get("family")
    result.latency_artificial = _scenario_state.get("artificial", False)
    result.ok = all(check.ok for check in result.checks)
    return result


_scenario_state: dict[str, Any] = {}


def _terminal_checks(case: EvalCase, outcome, checks: list[CheckResult]) -> None:
    """Senaryo terminal çıktısını örnek beklentileriyle denetler; sonuca yazar."""
    _scenario_state["terminal"] = _outcome_dict(outcome)
    _scenario_state["usage"] = {
        "model_calls": outcome.usage.model_calls,
        "tool_calls": outcome.usage.tool_calls,
        "web_search_calls": outcome.usage.web_search_calls,
    }
    if case.expected.status is not None:
        checks.append(_check("status", case.expected.status, outcome.status.value))
    if case.expected.status_in:
        actual = outcome.status.value
        checks.append(
            CheckResult("status_in", case.expected.status_in, actual, actual in case.expected.status_in)
        )
    if case.expected.error_code is not None:
        actual = outcome.error_code.value if outcome.error_code is not None else None
        checks.append(_check("error_code", case.expected.error_code, actual))
    if case.expected.mode is not None:
        checks.append(_check("mode", case.expected.mode, outcome.selected_mode.value))
    text = outcome.answer or outcome.report or ""
    checks.extend(_contains_check("answer", case.expected.answer_contains, text))
    checks.extend(_contains_check("report", case.expected.report_contains, outcome.report or ""))
    if case.expected.min_unresolved is not None:
        count = len(outcome.unresolved_questions)
        ok = count >= case.expected.min_unresolved
        checks.append(CheckResult("min_unresolved", f">={case.expected.min_unresolved}", count, ok))


async def _checkpoint_exists(store: FileCheckpointStore, run_id: str) -> bool:
    try:
        await load_resume_payload(store, run_id)
        return True
    except PortError:
        return False


async def _prepare(case: EvalCase, run_id: str, snapshot, store=None, execution_id: str | None = None):
    context = _make_context(case, run_id, snapshot)
    prepared = await prepare_and_route(context, checkpoint=store, execution_id=execution_id)
    _scenario_state["route_dict"] = _route_dict(prepared.route)
    return context, prepared


async def _scenario_collab_first(case, runtime, store, progress) -> list[CheckResult]:
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    _context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id], store=store)
    started = time.monotonic()
    outcome = await execute_plan(
        prepared,
        model=GroundedTestModel(),
        checkpoint=store,
        profile_repository=_ProfileRepo(),
        project_repository=_ProjectRepo(),
        article_catalog=_catalog(),
        progress=progress,
    )
    _scenario_state["elapsed"] = time.monotonic() - started
    checks: list[CheckResult] = []
    _terminal_checks(case, outcome, checks)
    stage = prepared.collab_state.stage.value if prepared.collab_state is not None else None
    if case.expected.collab_stage is not None:
        checks.append(_check("collab_stage", case.expected.collab_stage, stage))
    if case.expected.checkpoint_written:
        checks.append(_check("checkpoint_written", True, await _checkpoint_exists(store, run_id)))
    return checks


async def _scenario_collab_answers(case, runtime, store, progress, profile_repo, project_repo, catalog):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    _context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id], store=store)
    model = GroundedTestModel()
    # 1. adım: eksik detay sorusu (state checkpoint'e yazılır).
    await execute_plan(
        prepared,
        model=model,
        checkpoint=store,
        profile_repository=profile_repo,
        project_repository=project_repo,
        article_catalog=catalog,
    )
    # 2. adım: resume ile cevaplar → öneri.
    started = time.monotonic()
    outcome = await resume_entry(
        ResumeRequest(run_id=run_id, collab_input=_collab_answers_input()),
        store=store,
        progress=progress,
        profile_repository=profile_repo,
        project_repository=project_repo,
        article_catalog=catalog,
    )
    _scenario_state["elapsed"] = time.monotonic() - started
    checks: list[CheckResult] = []
    _terminal_checks(case, outcome, checks)
    checkpoint_prepared = await _load_prepared(store, run_id)
    stage = (
        checkpoint_prepared.collab_state.stage.value
        if checkpoint_prepared is not None and checkpoint_prepared.collab_state is not None
        else None
    )
    if case.expected.collab_stage is not None:
        checks.append(_check("collab_stage", case.expected.collab_stage, stage))
    if case.expected.checkpoint_written:
        checks.append(_check("checkpoint_written", True, checkpoint_prepared is not None))
    return checks


async def _scenario_collab_approval(case, runtime, store, progress, profile_repo, project_repo, catalog, *, verified: bool):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    _context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id], store=store)
    model = GroundedTestModel()
    await execute_plan(
        prepared, model=model, checkpoint=store,
        profile_repository=profile_repo, project_repository=project_repo, article_catalog=catalog,
    )
    await resume_entry(
        ResumeRequest(run_id=run_id, collab_input=_collab_answers_input()),
        store=store,
        profile_repository=profile_repo, project_repository=project_repo, article_catalog=catalog,
    )
    latest = await _load_prepared(store, run_id)
    assert latest is not None and latest.collab_state is not None and latest.collab_state.proposal is not None
    proposal = latest.collab_state.proposal
    checks: list[CheckResult] = []
    started = time.monotonic()
    if verified:
        validated = ValidatedActionResult(
            proposal_id=proposal.proposal_id,
            run_id=run_id,
            outcome="accepted",
            applied_article_revision=proposal.article_revision + 1,
            validated_at=fx.NOW,
        )
        outcome = await resume_entry(
            ResumeRequest(run_id=run_id, validated_result=validated),
            store=store,
            progress=progress,
            profile_repository=profile_repo, project_repository=project_repo, article_catalog=catalog,
        )
        _scenario_state["elapsed"] = time.monotonic() - started
        _terminal_checks(case, outcome, checks)
        final = await _load_prepared(store, run_id)
        stage = final.collab_state.stage.value if final is not None and final.collab_state is not None else None
        if case.expected.collab_stage is not None:
            checks.append(_check("collab_stage", case.expected.collab_stage, stage))
    else:
        # Sonucuz onay: resume doğrudan PortError(validation_error) fırlatmalı.
        raised = None
        try:
            await resume_entry(
                ResumeRequest(
                    run_id=run_id,
                    collab_input=CollabResumeInput(
                        approved_proposal_id=proposal.proposal_id,
                        approved_content_hash=latest.collab_state.proposal_content_hash,
                    ),
                ),
                store=store,
                profile_repository=profile_repo, project_repository=project_repo, article_catalog=catalog,
            )
        except PortError as error:
            raised = error
        _scenario_state["elapsed"] = time.monotonic() - started
        if case.expected.raises_error_code is not None:
            checks.append(
                CheckResult(
                    "raises_error_code", case.expected.raises_error_code,
                    raised.code.value if raised else None, raised is not None and raised.code.value == case.expected.raises_error_code,
                )
            )
    return checks


async def resume_entry(request: ResumeRequest, *, store, progress=None, profile_repository=None, project_repository=None, article_catalog=None):
    """``entrypoints.resume``'un koşucu kablolaması (model/retriever sabit).

    Retriever, checkpoint bağlamının makalesinden kurulur; böylece resume
    üretim kablolamasıyla aynı yoldan koşar.
    """
    prepared = await _load_prepared(store, request.run_id)
    retriever = None
    if prepared is not None and prepared.context.article_snapshot is not None:
        retriever = await _build_retriever_async(prepared.context.article_snapshot)
    return await resume(
        request,
        checkpoint=store,
        model=GroundedTestModel(),
        retriever=retriever,
        progress=progress,
        profile_repository=profile_repository,
        project_repository=project_repository,
        article_catalog=article_catalog,
    )


async def _load_prepared(store: FileCheckpointStore, run_id: str):
    _envelope, payload = await load_resume_payload(store, run_id)
    if payload is None:
        return None
    from agent_core.entrypoints import PreparedRun

    try:
        return PreparedRun.model_validate_json(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


async def _scenario_resume_after_cancel(case, runtime, store, progress):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    _context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id], store=store)
    model = GroundedTestModel()
    retriever = await _build_retriever_async(_context.article_snapshot)
    checks: list[CheckResult] = []

    cancelled = await execute_plan(prepared, model=model, retriever=retriever, cancel=PreCancelledToken())
    checks.append(_check("cancelled_status", "cancelled", cancelled.status.value))

    started = time.monotonic()
    outcome = await resume_entry(ResumeRequest(run_id=run_id), store=store, progress=progress)
    _scenario_state["elapsed"] = time.monotonic() - started
    _scenario_state["family"] = outcome.selected_mode.value
    _terminal_checks(case, outcome, checks)
    if case.expected.mode_preserved:
        checks.append(_check("mode_preserved", _scenario_state["route_dict"]["selected_mode"], outcome.selected_mode.value))
    if case.expected.progress_contains is not None:
        needle = case.expected.progress_contains.casefold()
        haystack = progress.text().casefold()
        checks.append(CheckResult("progress_contains", case.expected.progress_contains, needle in haystack, needle in haystack))

    # Yanlış yürütme kimliği reddi (aynı senaryonun bağlaşık denetimi).
    raised = None
    try:
        await resume_entry(
            ResumeRequest(run_id=run_id, execution_id=new_execution_id("other-run")),
            store=store,
        )
    except PortError as error:
        raised = error
    checks.append(
        CheckResult(
            "wrong_execution_rejected", "validation_error", raised.code.value if raised else None,
            raised is not None and raised.code.value == AgentErrorCode.VALIDATION_ERROR,
        )
    )
    return checks


async def _scenario_resume_deadline(case, runtime, store):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    _context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id], store=store)
    checks: list[CheckResult] = []
    started = time.monotonic()
    outcome = await resume(
        ResumeRequest(run_id=run_id, deadline_seconds=0.05),
        checkpoint=store,
        model=SlowTestModel(GroundedTestModel(), delay_seconds=0.5),
        retriever=await _build_retriever_async(_context.article_snapshot),
    )
    _scenario_state["elapsed"] = time.monotonic() - started
    _scenario_state["artificial"] = True  # yapay gecikme; gecikme metriklerinden hariç
    _terminal_checks(case, outcome, checks)
    return checks


async def _scenario_research_cancel(case, runtime):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id])
    model, _retriever, budget, web_tools, _p, _pr, _c = _execute_wiring(case, context, runtime)
    retriever = await _build_retriever_async(context.article_snapshot)
    checks: list[CheckResult] = []
    started = time.monotonic()
    outcome = await execute_plan(
        prepared,
        model=model,
        retriever=retriever,
        budget=budget,
        web_tools=web_tools,
        cancel=PreCancelledToken(),
    )
    _scenario_state["elapsed"] = time.monotonic() - started
    _terminal_checks(case, outcome, checks)
    return checks


async def _scenario_resume_stale(case, runtime, store, progress, *, stale: bool):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    snapshot = fx.EVAL_ARTICLES[case.article_id]
    _context, prepared = await _prepare(case, run_id, snapshot, store=store)
    checks: list[CheckResult] = []
    started = time.monotonic()
    if stale:
        # Gerileme: checkpoint revizyonundan ESKİ revizyona sahip bağlam.
        current_snapshot = snapshot.model_copy(update={"article_revision": snapshot.article_revision - 1})
        current = _make_context(case, run_id, current_snapshot)
        raised = None
        try:
            await resume_entry(ResumeRequest(run_id=run_id, current_context=current), store=store)
        except PortError as error:
            raised = error
        _scenario_state["elapsed"] = time.monotonic() - started
        if case.expected.raises_error_code is not None:
            checks.append(
                CheckResult(
                    "raises_error_code", case.expected.raises_error_code,
                    raised.code.value if raised else None,
                    raised is not None and raised.code.value == case.expected.raises_error_code,
                )
            )
        return checks
    # İlerleme: yeni revizyon (içerik ilerledi) → EVIDENCE_STALE ile sür.
    advanced_content = snapshot.content + "\n\n## İzleme panosu\n\nKuyruk bekleme süresi panoda grafik olarak izlenir."
    advanced_snapshot = snapshot.model_copy(
        update={
            "content": advanced_content,
            "content_hash": compute_content_hash(advanced_content),
            "article_revision": snapshot.article_revision + 1,
        }
    )
    current = _make_context(case, run_id, advanced_snapshot)
    model = GroundedTestModel()
    retriever = await _build_retriever_async(advanced_snapshot)
    outcome = await resume(
        ResumeRequest(run_id=run_id, current_context=current),
        checkpoint=store,
        model=model,
        retriever=retriever,
        progress=progress,
    )
    _scenario_state["elapsed"] = time.monotonic() - started
    _scenario_state["family"] = outcome.selected_mode.value
    _terminal_checks(case, outcome, checks)
    if case.expected.progress_contains is not None:
        needle = case.expected.progress_contains.casefold()
        haystack = progress.text().casefold()
        checks.append(CheckResult("progress_contains", case.expected.progress_contains, needle in haystack, needle in haystack))
    return checks


async def _scenario_resume_wrong_execution(case, runtime, store):
    run_id = f"eval-{case.case_id}"
    _scenario_state.clear()
    _context, prepared = await _prepare(case, run_id, fx.EVAL_ARTICLES[case.article_id], store=store)
    checks: list[CheckResult] = []
    started = time.monotonic()
    raised = None
    try:
        await resume_entry(
            ResumeRequest(run_id=run_id, execution_id=new_execution_id("baska-zincir")),
            store=store,
        )
    except PortError as error:
        raised = error
    _scenario_state["elapsed"] = time.monotonic() - started
    if case.expected.raises_error_code is not None:
        checks.append(
            CheckResult(
                "raises_error_code", case.expected.raises_error_code,
                raised.code.value if raised else None,
                raised is not None and raised.code.value == case.expected.raises_error_code,
            )
        )
    return checks


# --- cache senaryoları ----------------------------------------------------------


def _fingerprint(**overrides: Any) -> str:
    params = dict(
        embedding_model_id=EMBEDDING_MODEL_ID,
        qa_config=QaFlowConfig(),
        budget_profile_name="eval-default",
    )
    params.update(overrides)
    return config_fingerprint(**params)


def _key_for(context: ExecutionContext, fingerprint: str | None = None) -> str:
    snapshot = context.article_snapshot
    return answer_cache_key(
        content_hash=snapshot.content_hash if snapshot is not None else (context.article_content_hash or "-"),
        language=context.language,
        scope=question_scope(context),
        config_fingerprint_hex=fingerprint or _fingerprint(),
    )


def _run_cache_case(case: EvalCase, runtime: EvalRuntime) -> CaseResult:
    result = CaseResult(
        case_id=case.case_id, suite=case.suite, areas=case.areas, kind=case.kind, title=case.title
    )
    snapshot = fx.EVAL_ARTICLES[case.article_id]
    scenario = case.scenario

    if scenario == "cache_same_content_same_key":
        context_a = _make_context(case, "eval-c01-a", snapshot)
        context_b = _make_context(case, "eval-c01-b", snapshot)
        key_a, key_b = _key_for(context_a), _key_for(context_b)
        result.checks.append(_check("same_inputs_same_key", key_a, key_b))

    elif scenario == "cache_content_hash_changes_key":
        context_a = _make_context(case, "eval-c02-a", snapshot)
        advanced_content = snapshot.content + "\n\nYeni bölüm: ölçüm temelli sınır seçimi."
        advanced = snapshot.model_copy(
            update={"content": advanced_content, "content_hash": compute_content_hash(advanced_content)}
        )
        context_b = _make_context(case, "eval-c02-b", advanced)
        key_a, key_b = _key_for(context_a), _key_for(context_b)
        result.checks.append(CheckResult("content_hash_changes_key", "farklı", key_a != key_b, key_a != key_b))

    elif scenario == "cache_language_changes_key":
        context_tr = _make_context(case, "eval-c03-tr", snapshot)
        case_en = case.model_copy(update={"language": "en"})
        context_en = _make_context(case_en, "eval-c03-en", snapshot)
        key_tr, key_en = _key_for(context_tr), _key_for(context_en)
        result.checks.append(CheckResult("language_changes_key", "farklı", key_tr != key_en, key_tr != key_en))

    elif scenario == "cache_scope_changes_key":
        context_article = _make_context(case, "eval-c04-article", snapshot)
        context_general = _make_context(case, "eval-c04-general", None)
        context_selected = _make_context(case, "eval-c04-selected", snapshot)
        context_selected = context_selected.model_copy(update={"selected_text": "kuyruk"})
        scopes = {question_scope(c) for c in (context_article, context_general, context_selected)}
        result.checks.append(_check("scopes_distinct", 3, len(scopes)))
        keys = {_key_for(c) for c in (context_article, context_general, context_selected)}
        result.checks.append(CheckResult("scope_changes_key", 3, len(keys), len(keys) == 3))

    elif scenario == "cache_config_and_conversation":
        context_a = _make_context(case, "eval-c05-a", snapshot)
        key_a = _key_for(context_a, _fingerprint())
        key_b = _key_for(context_a, _fingerprint(prompt_template_version="eval-prompt-v2"))
        result.checks.append(CheckResult("config_version_changes_key", "farklı", key_a != key_b, key_a != key_b))
        history_context = _make_context(case, "eval-c05-hist", snapshot)
        history_context = history_context.model_copy(
            update={"conversation_history": [_make_history("user", "önceki soru")]}
        )
        selected_context = _make_context(case, "eval-c05-sel", snapshot)
        selected_context = selected_context.model_copy(update={"selected_text": "kuyruk"})
        result.checks.append(_check("plain_eligible", True, is_shared_cache_eligible(context_a)))
        result.checks.append(_check("history_not_shared", False, is_shared_cache_eligible(history_context)))
        result.checks.append(_check("selection_not_shared", False, is_shared_cache_eligible(selected_context)))
    else:
        result.checks.append(CheckResult("scenario", None, scenario, False))

    result.ok = all(check.ok for check in result.checks)
    return result


def _make_history(role: str, content: str):
    from agent_core.models import ConversationTurn

    return ConversationTurn(role=role, content=content, created_at=fx.NOW)


# --- ana koşu ------------------------------------------------------------------


def run_cases(suite: str = "all", *, runtime: EvalRuntime | None = None) -> list[CaseResult]:
    """Kümenin (veya bir suite'in) tüm örneklerini koşar; sonuç kayıtlarını döndürür."""
    own_runtime = runtime is None
    ctx = runtime or EvalRuntime()
    results: list[CaseResult] = []
    try:
        for case in cases_for_suite(suite):
            if case.kind == "route":
                results.append(_run_route_case(case, ctx))
            elif case.kind == "execute":
                results.append(_run_execute_case(case, ctx))
            elif case.kind == "resume":
                results.append(_run_resume_case(case, ctx))
            elif case.kind == "cache":
                results.append(_run_cache_case(case, ctx))
            else:
                raise ValueError(f"bilinmeyen örnek türü: {case.kind}")
    finally:
        if own_runtime:
            ctx.__exit__(None, None, None)
    return results
