"""Revizyon kapsam değerlendirmesi ve resume ayrımı testleri (A8).

Plan A8: "Tamamlanan kaynak ve araç sonuçlarını yeniden kullan", "yeni model
çağrısı gerektiren adımları önceki sonuçlardan ayır", "içerik revizyonu
değişirse eski checkpoint'in hangi kapsamda sürdürülebileceğini değerlendir".
Kabul senaryoları: içerik kaldırılması, revizyon ilerlemesi/gerilemesi,
kullanım kayıtlarının idempotentliği.
"""

from __future__ import annotations

import pytest

from agent_core.adapters.test_doubles import (
    ExplodingModelProvider,
    FakeCheckpointStore,
    FakeModelProvider,
)
from agent_core.checkpoint import FileCheckpointStore, ResumeScope, evaluate_resume, partition_for_resume
from agent_core.entrypoints import ResumeRequest, prepare_and_route, resume
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import RunStatus
from agent_core.state import deserialize_state, serialize_state
from agent_core.state.events import usage_record_from_events

from conftest import make_context, make_snapshot
from .conftest import make_state, make_usage_event, run

NEW_CONTENT_R4 = "# Güncel r4\n\nYeni içerik gövdesi."


def _evaluate(checkpoint_context, current_context):
    return evaluate_resume(checkpoint_context=checkpoint_context, current_context=current_context)


def test_full_reuse_when_same_revision() -> None:
    """Aynı revizyon: FULL_REUSE; tüm kanıt/bulgular yeniden kullanılır."""
    checkpoint_context = make_context(article_snapshot=make_snapshot())
    current = make_context(article_snapshot=make_snapshot())

    evaluation = _evaluate(checkpoint_context, current)

    assert evaluation.scope is ResumeScope.FULL_REUSE
    assert evaluation.resumable is True

    partition = partition_for_resume(make_state(), evaluation)
    assert partition.reusable_evidence_ids == ["ev-web-1", "ev-art-1"]
    assert partition.stale_evidence_ids == []
    assert partition.reusable_finding_ids == ["find-1"]
    assert partition.stale_finding_ids == []
    # Yeniden kullanım model çağrısı gerektirmez; rapor adı ayrı bir model adımıdır.
    assert partition.model_steps == ["finalize"]  # deep_research rotası


def test_evidence_stale_when_revision_advances() -> None:
    """Revizyon ilerledi: makale kanıtı/bulgu bayat; alt görev yeniden kuyruğa döner."""
    checkpoint_context = make_context(article_snapshot=make_snapshot())  # r3
    current = make_context(article_snapshot=make_snapshot(content=NEW_CONTENT_R4, article_revision=4))

    evaluation = _evaluate(checkpoint_context, current)
    assert evaluation.scope is ResumeScope.EVIDENCE_STALE
    assert evaluation.checkpoint_article_revision == 3
    assert evaluation.current_article_revision == 4
    assert "r3" in evaluation.reasons[0] and "r4" in evaluation.reasons[0]

    state = make_state()
    partition = partition_for_resume(state, evaluation)
    # Web kanıtı makaleden bağımsız → yeniden kullanılır; makale kanıtı bayat.
    assert partition.reusable_evidence_ids == ["ev-web-1"]
    assert partition.stale_evidence_ids == ["ev-art-1"]
    # Bulgu yalnız makale kanıtına dayanıyordu → bayat, alt soru yeniden kuyruğa girer.
    assert partition.stale_finding_ids == ["find-1"]
    assert partition.reusable_finding_ids == []
    assert {"sub_question": "S1: türler", "sub_index": 0, "round": 1} in [
        dict(t) for t in partition.pending_subtasks
    ]
    # Önceki bekleyen görev korunur; rapor adımı ayrı model adımıdır.
    assert {"sub_question": "S2: sınırlar", "sub_index": 1, "round": 1} in [
        dict(t) for t in partition.pending_subtasks
    ]
    assert partition.model_steps == ["finalize"]


def test_removed_content_not_resumable() -> None:
    """İÇERİK KALDIRILMASI senaryosu: devam stale_snapshot ile reddedilir, model çağrılmaz."""
    checkpoint_context = make_context(article_snapshot=make_snapshot())
    removed = make_context()  # makale referansı yok

    evaluation = _evaluate(checkpoint_context, removed)
    assert evaluation.scope is ResumeScope.NOT_RESUMABLE
    assert "kaldırılmış" in evaluation.reasons[0]

    # Giriş noktası düzeyinde: current_context ile devam reddi.
    store = FakeCheckpointStore()
    run(prepare_and_route(checkpoint_context, checkpoint=store))
    model = ExplodingModelProvider()

    with pytest.raises(PortError) as excinfo:
        run(
            resume(
                ResumeRequest(run_id=checkpoint_context.run_id, current_context=removed),
                checkpoint=store,
                model=model,
            )
        )
    assert excinfo.value.code is AgentErrorCode.STALE_SNAPSHOT
    assert "kaldırılmış" in excinfo.value.message
    assert model.call_count == 0


def test_revision_regression_not_resumable() -> None:
    """Revizyon gerilemesi (monotonluk — D008): devam reddedilir."""
    checkpoint_context = make_context(article_snapshot=make_snapshot())  # r3
    older = make_context(article_snapshot=make_snapshot(article_revision=2))

    evaluation = _evaluate(checkpoint_context, older)
    assert evaluation.scope is ResumeScope.NOT_RESUMABLE
    assert "gerileme" in evaluation.reasons[0]


def test_other_article_not_resumable() -> None:
    """Checkpoint başka makaleye bağlıyken devam edilmez."""
    checkpoint_context = make_context(article_snapshot=make_snapshot())  # post-1
    other = make_context(article_snapshot=make_snapshot(article_id="post-2"))

    evaluation = _evaluate(checkpoint_context, other)
    assert evaluation.scope is ResumeScope.NOT_RESUMABLE


def test_resume_stale_scope_continues_with_current_context(tmp_path) -> None:
    """EVIDENCE_STALE: çalışma GÜNCEL bağlamla sürer; rota korunur, model güncel içeriği görür."""
    store = FileCheckpointStore(tmp_path)
    checkpoint_context = make_context(article_snapshot=make_snapshot())  # r3
    run(prepare_and_route(checkpoint_context, checkpoint=store))

    current = make_context(article_snapshot=make_snapshot(content=NEW_CONTENT_R4, article_revision=4))
    model = FakeModelProvider("güncel bağlamdan yanıt")

    outcome = run(
        resume(
            ResumeRequest(run_id=checkpoint_context.run_id, current_context=current),
            checkpoint=store,
            model=model,
        )
    )

    assert outcome.status is RunStatus.COMPLETED
    assert model.call_count == 1
    # Güncel bağlam devrede: model prompt'u YENİ revizyon içeriğini taşır.
    assert "Güncel r4" in model.requests[0].prompt


def test_usage_records_idempotent_across_reexecution() -> None:
    """Yeniden yürütülebilen node'lar: aynı eylem kimliği → kullanım kaydı çift sayılmaz.

    Ayrım kanıtı: tamamlanmış sonuç (event_id kararlı) resume sınırının iki
    tarafında birleşse bile kullanım görünümü tek çağrı sayar.
    """
    first_attempt = make_usage_event("subtask:1:search#1", "subtask:1:search")
    # Aynı eylemin checkpoint sonrası tekrar yürütülmesi AYNI event_id üretir.
    rerun_attempt = make_usage_event("subtask:1:search#1", "subtask:1:search")

    merged = usage_record_from_events(
        "run-a8", [first_attempt, rerun_attempt], duration_seconds=1.0
    )
    assert merged.model_calls == 1
    assert merged.total_tokens == first_attempt.total_tokens  # tokenlar da tek sayılır


def test_partition_survives_state_roundtrip_through_checkpoint() -> None:
    """State checkpoint'e yazılıp geri yüklendikten sonra ayrım aynı sonucu verir."""
    state = make_state()
    payload = serialize_state(state)
    restored = deserialize_state(payload, expected_run_id="run-a8")

    direct = partition_for_resume(state)
    after_roundtrip = partition_for_resume(restored)

    assert direct == after_roundtrip
    assert after_roundtrip.state_schema_version == state["schema_version"]
