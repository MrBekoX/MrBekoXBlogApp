"""Resume giriş noktasının A8 davranışları: zarf sözleşmeleri, iptal, deadline.

Plan A8: "İptal ve deadline'ı devam ettirilen çalışmada da uygula", kararlı
yürütme kimliği bağlaması, uyumsuz checkpoint'in anlaşılır reddi ve A1 dönemi
ham payload'la geriye dönük uyumluluk.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_core.adapters.test_doubles import (
    ExplodingModelProvider,
    FakeModelProvider,
    PreCancelledToken,
)
from agent_core.checkpoint import CheckpointKind, FileCheckpointStore, save_checkpoint
from agent_core.checkpoint.models import CheckpointEnvelope
from agent_core.entrypoints import ResumeRequest, prepare_and_route, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import RunStatus

from conftest import make_context, make_snapshot
from .conftest import SlowModelProvider, Stopwatch, run

ROOT_NOW = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc)


def _prepare_with_file_store(store: FileCheckpointStore):
    """Hazırlığı koşar, ham checkpoint yazar; PreparedRun döndürür."""
    context = make_context(article_snapshot=make_snapshot())
    return run(prepare_and_route(context, checkpoint=store))


def _wrap_prepared(prepared, checkpoint_id: str, schema_version: int | None = None):
    """PreparedRun payload'ını zarflayıp döndürür (yazım test içinde ayrı yapılır)."""
    envelope = CheckpointEnvelope.wrap(
        checkpoint_id=checkpoint_id,
        run_id=prepared.context.run_id,
        execution_id=prepared.execution_id or "exec-x",
        kind=CheckpointKind.PREPARED,
        payload=prepared.model_dump_json().encode("utf-8"),
        saved_at=ROOT_NOW,
        context=prepared.context,
    )
    if schema_version is not None:
        envelope = envelope.model_copy(update={"schema_version": schema_version})
    return envelope


def test_resume_with_envelope_and_matching_execution_id_completes(tmp_path) -> None:
    """Zarflı checkpoint + eşleşen yürütme kimliği: çalışma sürer, rota yeniden hesaplanmaz."""
    store = FileCheckpointStore(tmp_path)
    prepared = _prepare_with_file_store(store)
    envelope = _wrap_prepared(prepared, "prepared:exec-zincir")
    run(store.save(prepared.context.run_id, envelope.checkpoint_id,
                   envelope.model_dump_json().encode("utf-8")))
    model = FakeModelProvider("sürdürülmüş yanıt")

    outcome = run(
        resume(
            ResumeRequest(run_id=prepared.context.run_id, execution_id=prepared.execution_id),
            checkpoint=store,
            model=model,
        )
    )

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer == "sürdürülmüş yanıt"
    assert model.call_count == 1  # yalnız yanıt üretimi; router çağrısı yok


def test_resume_rejects_mismatched_execution_id(tmp_path) -> None:
    """Farklı yürütme zincirinin kimliği: anlaşılır validation_error, model çağrılmaz."""
    store = FileCheckpointStore(tmp_path)
    prepared = _prepare_with_file_store(store)
    envelope = _wrap_prepared(prepared, "prepared:exec-zincir")
    run(store.save(prepared.context.run_id, envelope.checkpoint_id,
                   envelope.model_dump_json().encode("utf-8")))
    model = ExplodingModelProvider()

    with pytest.raises(PortError) as excinfo:
        run(
            resume(
                ResumeRequest(run_id=prepared.context.run_id, execution_id="exec-baska-zincir"),
                checkpoint=store,
                model=model,
            )
        )

    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "yürütme kimliği" in excinfo.value.message
    assert "exec-baska-zincir" in excinfo.value.message
    assert model.call_count == 0


def test_resume_with_future_envelope_version_fails_clearly(tmp_path) -> None:
    """Giriş noktasında uyumsuz zarf sürümü anlaşılır validation_error üretir."""
    store = FileCheckpointStore(tmp_path)
    prepared = _prepare_with_file_store(store)
    envelope = _wrap_prepared(prepared, "prepared:exec-future", schema_version=999)
    run(store.save(prepared.context.run_id, envelope.checkpoint_id,
                   envelope.model_dump_json().encode("utf-8")))

    with pytest.raises(PortError) as excinfo:
        run(
            resume(
                ResumeRequest(run_id=prepared.context.run_id),
                checkpoint=store,
                model=ExplodingModelProvider(),
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "v999" in excinfo.value.message


def test_resume_legacy_raw_payload_still_loads(tmp_path) -> None:
    """A1 dönemi ham payload (zarfsız, yürütme kimliği taşımaz) aynen sürdürülür."""
    store = FileCheckpointStore(tmp_path)
    context = make_context(article_snapshot=make_snapshot())
    prepared = run(prepare_and_route(context))
    # Ham payload doğrudan yazılır: zarfsız eski checkpoint'i temsil eder.
    run(store.save(context.run_id, "prepared:run", prepared.model_dump_json().encode("utf-8")))
    model = FakeModelProvider("eski biçimden sürüldü")

    outcome = run(
        resume(ResumeRequest(run_id=context.run_id), checkpoint=store, model=model)
    )

    assert outcome.status is RunStatus.COMPLETED
    assert outcome.answer == "eski biçimden sürüldü"


def test_resume_deadline_expires_mid_call(tmp_path) -> None:
    """DEVAM ETTİRİLEN çalışmada deadline uygulanır: model çağrısı kesilir, süreç asılı kalmaz."""
    store = FileCheckpointStore(tmp_path)
    context = make_context(article_snapshot=make_snapshot())
    run(prepare_and_route(context, checkpoint=store))
    slow_model = SlowModelProvider(delay_seconds=2.0)

    watch = Stopwatch()
    outcome = run(
        resume(
            ResumeRequest(run_id=context.run_id, deadline_seconds=0.2),
            checkpoint=store,
            model=slow_model,
        )
    )
    elapsed = watch.elapsed()

    assert outcome.status is RunStatus.FAILED
    assert outcome.error_code is AgentErrorCode.TIMEOUT
    assert outcome.answer is None
    assert slow_model.call_count == 1  # çağrı açıldı ama süresi içinde dönmedi
    assert elapsed < 1.5, f"deadline uygulanmadı, çalışma {elapsed:.2f}s sürdü"


def test_resume_rejects_nonpositive_deadline(tmp_path) -> None:
    """Geçersiz süre sınırı anlaşılır validation_error ile reddedilir; model çağrılmaz."""
    store = FileCheckpointStore(tmp_path)
    context = make_context(article_snapshot=make_snapshot())
    run(prepare_and_route(context, checkpoint=store))
    model = ExplodingModelProvider()

    with pytest.raises(PortError) as excinfo:
        run(
            resume(
                ResumeRequest(run_id=context.run_id, deadline_seconds=0),
                checkpoint=store,
                model=model,
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "deadline" in excinfo.value.message
    assert model.call_count == 0


def test_resume_cancel_enforced_in_resumed_run(tmp_path) -> None:
    """İptal sinyali devam ettirilen çalışmada da uygulanır; model hiç çağrılmaz."""
    store = FileCheckpointStore(tmp_path)
    context = make_context(article_snapshot=make_snapshot())
    run(prepare_and_route(context, checkpoint=store))
    model = ExplodingModelProvider()

    with pytest.raises(PortError) as excinfo:
        run(
            resume(
                ResumeRequest(run_id=context.run_id),
                checkpoint=store,
                model=model,
                cancel=PreCancelledToken("kullanıcı iptal etti"),
            )
        )

    assert excinfo.value.code is AgentErrorCode.CANCELLED
    assert model.call_count == 0
