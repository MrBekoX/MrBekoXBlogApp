"""Graph yürütücü: paralel bütçe, iptal, deadline, checkpoint ve kullanım.

Plan A2 kabul ölçütleri bu dosyada graph ölçeğinde doğrulanır:
- Paralel görevlerle bütçe sınırı aşılamıyor (atomik rezervasyon).
- İptal edilmiş çalışma yeni araç çağrısı başlatmıyor.
- State checkpoint'e yazılıp geri yüklenebiliyor.
- Kullanım kayıtları tekrar yürütmede kopya oluşturmuyor.

Testler gerçek langgraph (1.0.6) kurulumuyla koşar; etkiler deterministik
double'dır — başarılar gerçek sağlayıcı başarısı değildir.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver

from agent_core.adapters.test_doubles import FakeCheckpointStore
from agent_core.budget import BudgetPolicy
from agent_core.errors import AgentErrorCode
from agent_core.graph import SubtaskOutcome, run_agent_graph
from agent_core.models import (
    AgentMode,
    ArticleSnapshot,
    RunStatus,
    compute_content_hash,
)
from agent_core.ports import BudgetKind
from agent_core.state import (
    InMemoryArtifactStore,
    deserialize_state,
    merge_usage_events,
    usage_record_from_events,
)

from effects import (
    MutableToken,
    ScriptedEffects,
    make_run_context,
    make_route,
    ok,
    run_graph,
)

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)


class ConcurrencyProbe(ScriptedEffects):
    """Eşzamanlı worker tepe sayısını ölçen etkiler."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.active = 0
        self.max_active = 0

    async def run_subtask(self, task, tasks) -> SubtaskOutcome:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            return await super().run_subtask(task, tasks)
        finally:
            self.active -= 1


class CancelMidSubtaskEffects(ScriptedEffects):
    """İlk araç çağrısından sonra iptal eden etkiler: sonraki çağrılar başlamamalı."""

    async def run_subtask(self, task, tasks) -> SubtaskOutcome:
        index = task["sub_index"]
        await tasks.guarded(
            action_id=f"subtask:{index}:search",
            kind=BudgetKind.WEB_SEARCH_CALL,
            call=self._tracked(f"subtask:{index}:search", ok([f"hit-{index}"])),
        )
        tasks.cancel.cancel()  # ilk çağrı tamamlandıktan sonra iptal
        # Sonraki çağrı guard girişinde reddedilmeli; bu satıra dönüş olmaz.
        await tasks.guarded(
            action_id=f"subtask:{index}:read",
            kind=BudgetKind.SOURCE_PAGE_READ,
            call=self._tracked(f"subtask:{index}:read", ok("yasak")),
        )
        raise AssertionError("iptal sonrası ikinci çağrıya ulaşmamalı")

    def _tracked(self, name, call):
        async def wrapper(attempt):
            self.started_calls.append(name)
            result = await call(attempt)
            self.completed_calls.append(name)
            return result

        return wrapper


class SlowEffects(ScriptedEffects):
    """Her alt görevde süre sınırını kesin aşan gecikme."""

    async def run_subtask(self, task, tasks) -> SubtaskOutcome:
        await asyncio.sleep(0.12)
        return await super().run_subtask(task, tasks)


def test_deep_research_completes_within_policy_limits() -> None:
    """5 alt soru → 4'e kırpılır; paralellik ≤ 3; tur ≤ 2; sonuç completed."""
    effects = ConcurrencyProbe()
    context = make_run_context()

    result = run_graph(context, make_route(context), effects)

    assert result.outcome.status is RunStatus.COMPLETED
    plan = result.state["plan"]
    assert len(plan.sub_questions) == 4  # politika sınırı (5 tekliften kırpıldı)
    assert effects.max_active <= 3  # max_parallel_subtasks
    assert result.state["research_round"] <= 2  # ilk tur dahil 2 tur
    usage = result.outcome.usage
    assert usage.model_calls == 5  # 4 alt görev cevabı + 1 rapor
    assert usage.web_search_calls == 4
    assert len(result.state["findings"]) == 4
    assert len(result.state["evidence"]) == 4
    assert result.state["messages"][-1].role == "assistant"  # asistan cevabı state'te


def test_state_checkpoint_roundtrip_after_run() -> None:
    """Yürütüm sonrası state CheckpointStore'a yazılır ve geri yüklenir."""
    store = FakeCheckpointStore()
    artifacts = InMemoryArtifactStore()
    context = make_run_context()

    run_graph(context, make_route(context), ScriptedEffects(), artifacts=artifacts, checkpoint=store)

    checkpoint_id, payload = asyncio.run(store.load_latest("run-a2"))
    assert checkpoint_id == "a2-state"
    restored = deserialize_state(payload, expected_run_id="run-a2")
    assert len(restored["findings"]) == 4
    assert restored["route"].selected_mode is AgentMode.DEEP_RESEARCH
    assert restored["outcome"] is not None  # terminal sonuç state'te
    assert b"xxxxx" not in payload  # büyük sayfa metni checkpoint'te değil
    ref = restored["artifact_refs"][0]
    assert "alt-" in artifacts.get("run-a2", ref.artifact_id)


def test_langgraph_checkpointer_persists_superstep_state() -> None:
    """LangGraph MemorySaver superstep state'ini thread'e yazar [LG-PERSISTENCE#C1]."""
    checkpointer = MemorySaver()
    context = make_run_context()

    result = run_graph(context, make_route(context), ScriptedEffects(), langgraph_checkpointer=checkpointer)

    snapshot = result.compiled.get_state({"configurable": {"thread_id": "run-a2"}})
    assert snapshot is not None
    values = snapshot.values
    assert values["findings"], "checkpoint'te bulgular olmalı"
    assert values["outcome"].status is RunStatus.COMPLETED


def test_budget_exhaustion_in_parallel_subtasks_ends_partial() -> None:
    """Arama bütçesi bitince kalan çağrılar reddedilir; tamamlanan bulgularla kısmi rapor kurulur.

    Sıralı tur (paralellik 1): ilk alt görev tamamlanır, ikinci turda bütçe reddi
    graph'ı bitirir; checkpoint'ten okunan son superstep state'i mekanik kısmi
    rapora girer.
    """
    context = make_run_context()
    policy = BudgetPolicy(
        max_sub_questions=4, max_search_calls=1, max_source_pages=12,
        max_research_rounds=2, max_parallel_subtasks=1, max_model_calls=16,
        max_total_tokens=50_000, max_tool_attempts=24, max_duration_seconds=60.0,
    )
    effects = ScriptedEffects(sub_questions=("S1", "S2"))

    result = run_graph(
        context, make_route(context), effects, policy=policy, langgraph_checkpointer=MemorySaver()
    )

    assert result.outcome.status is RunStatus.PARTIAL
    assert result.outcome.error_code is AgentErrorCode.BUDGET_EXHAUSTED
    assert result.outcome.report is not None  # mevcut bulgulardan mekanik özet
    assert result.outcome.usage.web_search_calls <= 1


def test_cancelled_run_starts_no_new_tool_calls() -> None:
    """İptal edilmiş çalışma yeni araç çağrısı başlatmaz (kabul ölçütü)."""
    effects = ScriptedEffects(sub_questions=("S1",))
    token = MutableToken()

    async def cancel_at_entry(task, tasks) -> None:
        token.cancel()  # etkilerin ilk çağrısından önce

    effects.on_subtask = cancel_at_entry
    context = make_run_context()

    result = run_graph(context, make_route(context), effects, cancel=token)

    assert result.outcome.status is RunStatus.CANCELLED
    assert effects.started_calls == []  # iptal edilmiş çalışma çağrı başlatmadı


def test_cancel_mid_subtask_blocks_following_calls() -> None:
    """Alt görev ortasında iptal: sonraki araç çağrıları başlamaz; tamamlanan sayılır."""
    effects = CancelMidSubtaskEffects(sub_questions=("S1",))
    token = MutableToken()
    context = make_run_context()

    result = run_graph(context, make_route(context), effects, cancel=token)

    assert result.outcome.status is RunStatus.CANCELLED
    assert effects.started_calls == ["subtask:0:search"]
    assert effects.completed_calls == ["subtask:0:search"]


def test_deadline_exceeded_ends_terminal() -> None:
    """Süre sınırı node ve çağrı sınırlarında denetlenir; terminal timeout sonucu."""
    context = make_run_context()
    policy = BudgetPolicy(max_duration_seconds=0.03)
    effects = SlowEffects(sub_questions=("S1",))

    result = run_graph(context, make_route(context), effects, policy=policy)

    assert result.outcome.status is RunStatus.FAILED
    assert result.outcome.error_code is AgentErrorCode.TIMEOUT


def test_fast_mode_answers_without_research_nodes() -> None:
    """fast yolu plan/subtask çalıştırmaz; cevap state'e ve mesaja yazılır."""
    context = make_run_context(mode_preference="fast")
    effects = ScriptedEffects()

    result = run_graph(context, make_route(context, AgentMode.FAST), effects)

    assert result.outcome.status is RunStatus.COMPLETED
    assert result.outcome.answer == "test cevabı"
    assert result.outcome.report is None
    assert result.state.get("plan") is None
    assert effects.run_subtasks == 0
    assert result.outcome.usage.model_calls == 1


def test_reexecution_of_same_actions_yields_no_duplicate_usage() -> None:
    """Aynı eylemler yeniden yürütülse (aynı event_id) birleşim kopya sayım üretmez."""
    context = make_run_context()
    route = make_route(context)
    store = InMemoryArtifactStore()

    first = run_graph(context, route, ScriptedEffects(), artifacts=store)
    second = run_graph(context, route, ScriptedEffects(), artifacts=store)

    merged = merge_usage_events(
        [], list(first.state["usage_events"]) + list(second.state["usage_events"])
    )
    assert len(merged) == len(second.state["usage_events"])  # kopya yok: aynı kimlik kümesi
    usage = usage_record_from_events("run-a2", merged)
    assert usage.model_calls == second.outcome.usage.model_calls


def test_stale_snapshot_fails_fast_in_prepare() -> None:
    """Snapshot hash'i bozuksa graph terminal ``stale_snapshot`` ile biter."""
    content = "# Makale\n\nBu içerik bilinçli bozulur."
    snapshot = ArticleSnapshot(
        article_id="post-9",
        slug="makale",
        title="Makale",
        content=content,
        content_hash="0" * 64,  # gerçek özetle uyuşmaz
        article_revision=2,
        fetched_at=NOW,
    )
    context = make_run_context(
        article_snapshot=snapshot,
        article_id=snapshot.article_id,
        article_revision=snapshot.article_revision,
        article_content_hash=snapshot.content_hash,
    )
    assert compute_content_hash(content) != snapshot.content_hash

    result = run_graph(context, make_route(context), ScriptedEffects())

    assert result.outcome.status is RunStatus.FAILED
    assert result.outcome.error_code is AgentErrorCode.STALE_SNAPSHOT
