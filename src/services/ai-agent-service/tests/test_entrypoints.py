"""Giriş noktası davranış testleri.

Kabul ölçütü: "Paket dış adaptör olmadan test girdisiyle çağrılabilir" —
tüm akışlar test double'larla koşar. Kritik plan kuralı: router kararı bir
kez hesaplanır, execute/resume yeniden model çağrısıyla hesaplamaz
(plan A1, ``01-agent-gelistirme-plani.md:186``).
"""

from __future__ import annotations

import pytest

from agent_core.adapters.test_doubles import (
    ExplodingModelProvider,
    FakeBudgetStore,
    FakeCheckpointStore,
    FakeModelProvider,
    PreCancelledToken,
    RecordingProgressSink,
    StubCancellationToken,
)
from agent_core.entrypoints import PreparedRun, ResumeRequest, execute_plan, prepare_and_route, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import ProgressKind, RunStatus
from agent_core.ports import BudgetKind, CancellationToken

import conftest


class CancelAfterEntryToken:
    """İlk kontrolü geçer, ikinci kontrolde (model çağrısı sırasında) iptal eder."""

    is_test_double = True

    def __init__(self) -> None:
        self._checks = 0

    def is_cancelled(self) -> bool:
        return self._checks >= 1

    def reason(self) -> str | None:
        return "kullanıcı iptal etti"

    def raise_if_cancelled(self) -> None:
        self._checks += 1
        if self._checks >= 2:
            raise PortError(
                AgentErrorCode.CANCELLED, f"çalışma iptal edildi: {self.reason()}",
                port="CancellationToken",
            )


def make_prepared(**context_overrides):
    context = conftest.make_context(**context_overrides)
    prepared = conftest.run(prepare_and_route(context))
    return prepared


def test_prepare_routes_without_any_model_call() -> None:
    exploding = ExplodingModelProvider()

    prepared = conftest.run(
        prepare_and_route(conftest.make_context(), progress=None, cancel=StubCancellationToken())
    )

    assert prepared.route.selected_mode.value == "fast"
    assert exploding.call_count == 0


def test_prepare_honors_explicit_mode_preference() -> None:
    prepared = make_prepared(mode_preference="analysis")

    assert prepared.route.selected_mode.value == "analysis"
    assert "tercih" in prepared.route.reason


def test_auto_routes_research_signal_to_deep_research() -> None:
    prepared = make_prepared(
        question="Python tip ipuçlarının güncel durumunu araştır ve karşılaştır"
    )

    assert prepared.route.selected_mode.value == "deep_research"
    assert prepared.route.requires_web_search is True


def test_auto_routes_selection_to_analysis() -> None:
    prepared = make_prepared(
        question="Bu bölüm ne diyor?",
        selected_text="def add(a: int, b: int) -> int: return a + b",
    )

    assert prepared.route.selected_mode.value == "analysis"


def test_prepare_rejects_stale_snapshot_with_common_error_code() -> None:
    snapshot = conftest.make_snapshot()
    stale = conftest.make_snapshot(content="# Farklı içerik\n\nGövde.")

    with pytest.raises(PortError) as excinfo:
        conftest.run(
            prepare_and_route(
                conftest.make_context(
                    article_snapshot=stale,
                    article_id=snapshot.article_id,
                    article_revision=snapshot.article_revision,
                    article_content_hash=snapshot.content_hash,
                )
            )
        )

    assert excinfo.value.code is AgentErrorCode.STALE_SNAPSHOT


def test_prepare_rejects_snapshot_with_corrupt_hash_field() -> None:
    content = "# Merhaba\n\nGövde."
    corrupt = conftest.make_snapshot(content=content, content_hash=conftest.compute_content_hash("başka içerik"))

    with pytest.raises(PortError) as excinfo:
        conftest.run(
            prepare_and_route(
                conftest.make_context(
                    article_snapshot=corrupt,
                    article_id=corrupt.article_id,
                    article_revision=corrupt.article_revision,
                    article_content_hash=corrupt.content_hash,
                )
            )
        )

    assert excinfo.value.code is AgentErrorCode.STALE_SNAPSHOT


def test_prepare_accepts_reference_only_context() -> None:
    # K7: içerik gömülmez, yalnız revizyon/hash referansı taşınır.
    context = conftest.make_context(
        article_id="post-1",
        article_revision=3,
        article_content_hash=conftest.compute_content_hash(conftest.ARTICLE_CONTENT),
    )

    prepared = conftest.run(prepare_and_route(context))

    assert prepared.context.article_snapshot is None


def test_prepare_publishes_progress_events() -> None:
    sink = RecordingProgressSink()

    conftest.run(prepare_and_route(conftest.make_context(article_snapshot=conftest.make_snapshot()), progress=sink))

    kinds = [event.kind for event in sink.events]
    assert kinds == [
        ProgressKind.RUN_STARTED,
        ProgressKind.ARTICLE_CONTEXT_READY,
        ProgressKind.MODE_SELECTED,
    ]


def test_prepare_cancelled_before_start() -> None:
    with pytest.raises(PortError) as excinfo:
        conftest.run(prepare_and_route(conftest.make_context(), cancel=PreCancelledToken("kullanıcı")))

    assert excinfo.value.code is AgentErrorCode.CANCELLED


def test_execute_completes_with_usage_and_budget_commit() -> None:
    prepared = make_prepared()
    model = FakeModelProvider("Hesaplanan yanıt")
    budget = FakeBudgetStore()
    sink = RecordingProgressSink()

    outcome = conftest.run(execute_plan(prepared, model=model, budget=budget, progress=sink))

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer == "Hesaplanan yanıt"
    assert outcome.report is None
    assert outcome.usage.model_calls == 1
    assert outcome.usage.total_tokens == 15
    assert outcome.usage.run_id == prepared.context.run_id
    assert budget.committed[BudgetKind.MODEL_CALL] == 15
    assert [event.kind for event in sink.events] == [
        ProgressKind.GENERATION_STARTED,
        ProgressKind.GENERATION_COMPLETED,
    ]


def test_execute_uses_prepared_route_and_does_not_reroute() -> None:
    prepared = make_prepared(mode_preference="analysis")
    model = FakeModelProvider("satır satır açıklama")

    outcome = conftest.run(execute_plan(prepared, model=model))

    assert outcome.selected_mode.value == "analysis"
    assert model.call_count == 1
    assert model.requests[0].metadata["mode"] == "analysis"


def test_execute_deep_research_produces_report_not_answer() -> None:
    prepared = make_prepared(question="Konuyu derinlemesine araştır ve rapor hazırla")
    assert prepared.route.selected_mode.value == "deep_research"

    outcome = conftest.run(execute_plan(prepared, model=FakeModelProvider("# Rapor\n\nBulgular.")))

    assert outcome.report is not None
    assert outcome.answer is None
    assert outcome.source_scope.value == "article_and_web"


def test_execute_cancelled_during_model_call() -> None:
    prepared = make_prepared()
    model = FakeModelProvider()

    outcome = conftest.run(execute_plan(prepared, model=model, cancel=CancelAfterEntryToken()))

    assert outcome.status is RunStatus.CANCELLED
    assert outcome.error_code is None
    assert outcome.error_message is not None
    assert model.call_count == 0


def test_execute_budget_exhaustion_fails_before_model_call() -> None:
    prepared = make_prepared()
    model = FakeModelProvider()
    budget = FakeBudgetStore(model_call_capacity=0)

    outcome = conftest.run(execute_plan(prepared, model=model, budget=budget))

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.BUDGET_EXHAUSTED
    assert model.call_count == 0
    assert not budget.releases  # rezervasyon oluşamadı, release edilecek şey yok


def test_execute_provider_error_releases_reservation() -> None:
    prepared = make_prepared()

    class FailingModel(FakeModelProvider):
        async def complete(self, request, *, cancel: CancellationToken | None = None):
            if cancel is not None:
                cancel.raise_if_cancelled()
            raise PortError(AgentErrorCode.PROVIDER_ERROR, "sağlayıcı yanıt vermiyor", port="ModelProvider")

    model = FailingModel()
    budget = FakeBudgetStore()

    outcome = conftest.run(execute_plan(prepared, model=model, budget=budget))

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.PROVIDER_ERROR
    assert len(budget.releases) == 1


def test_progress_sink_failure_does_not_break_execution() -> None:
    prepared = make_prepared()
    sink = RecordingProgressSink(
        fail_with=PortError(AgentErrorCode.PROVIDER_ERROR, "progress kanalı kapalı", port="ProgressSink")
    )

    outcome = conftest.run(execute_plan(prepared, model=FakeModelProvider(), progress=sink))

    assert outcome.status is RunStatus.COMPLETED


def test_resume_restores_route_from_checkpoint_without_rerouting() -> None:
    store = FakeCheckpointStore()
    prepared = conftest.run(
        prepare_and_route(conftest.make_context(article_snapshot=conftest.make_snapshot()), checkpoint=store)
    )
    model = FakeModelProvider("sürdürülmüş yanıt")

    outcome = conftest.run(
        resume(ResumeRequest(run_id="run-1"), checkpoint=store, model=model)
    )

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer == "sürdürülmüş yanıt"
    assert outcome.selected_mode == prepared.route.selected_mode
    assert model.call_count == 1

    checkpoint_id, payload = conftest.run(store.load_latest("run-1"))
    # Üretim yazımı sürümlü zarfladır (W5 bulgusu 3): payload zarf JSON'u;
    # PreparedRun zarfın gövdesinden çözümlenir.
    from agent_core.checkpoint.models import CheckpointEnvelope

    envelope = CheckpointEnvelope.model_validate_json(payload.decode("utf-8"))
    assert checkpoint_id == envelope.checkpoint_id
    assert checkpoint_id == "prepared:run"
    assert envelope.run_id == "run-1"
    assert envelope.execution_id == prepared.execution_id
    restored = PreparedRun.model_validate_json(envelope.payload_bytes().decode("utf-8"))
    assert restored.route == prepared.route
    assert restored.context == prepared.context


def test_resume_with_unknown_run_raises_not_found() -> None:
    store = FakeCheckpointStore()

    with pytest.raises(PortError) as excinfo:
        conftest.run(resume(ResumeRequest(run_id="run-404"), checkpoint=store, model=FakeModelProvider()))

    assert excinfo.value.code is AgentErrorCode.NOT_FOUND


def test_resume_with_corrupt_payload_raises_validation_error() -> None:
    store = FakeCheckpointStore()
    conftest.run(store.save("run-1", "prepared:run", b"{bozuk json"))

    with pytest.raises(PortError) as excinfo:
        conftest.run(resume(ResumeRequest(run_id="run-1"), checkpoint=store, model=FakeModelProvider()))

    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR


def test_resume_with_foreign_run_payload_raises_validation_error() -> None:
    store = FakeCheckpointStore()
    conftest.run(
        prepare_and_route(conftest.make_context(), checkpoint=store)
    )
    # run-1 payload'ı run-2 anahtarına kopyalanır: depo erişimi başarılı olur ama
    # payload başka bir çalışmaya aittir.
    _, payload = conftest.run(store.load_latest("run-1"))
    conftest.run(store.save("run-2", "prepared:run", payload))

    with pytest.raises(PortError) as excinfo:
        conftest.run(
            resume(ResumeRequest(run_id="run-2", checkpoint_id="prepared:run"), checkpoint=store, model=FakeModelProvider())
        )

    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
