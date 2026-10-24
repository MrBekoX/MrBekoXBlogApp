"""Checkpoint zarfı, şema sürümleri ve kararlı yürütme kimliği testleri (A8).

Plan A8: "State ve checkpoint şema sürümlerini tanımla", "uyumsuz eski
checkpoint için anlaşılır sonuç üret", "her çalıştırmaya dış adaptörün
doğruladığı kararlı bir yürütme kimliğiyle checkpoint bağla".
"""

from __future__ import annotations

import pytest

from agent_core.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    FileCheckpointStore,
    CheckpointEnvelope,
    CheckpointKind,
    load_resume_payload,
    new_execution_id,
    save_checkpoint,
    validate_execution_id,
)
from agent_core.errors import AgentErrorCode, PortError
from agent_core.state import STATE_SCHEMA_VERSION, deserialize_state, serialize_state

from .conftest import NOW, make_state, run


def test_execution_id_validation_and_generation() -> None:
    """Dış adaptörün doğrulama sözleşmesi: biçim denetimi ve kararlı üretim."""
    assert validate_execution_id("exec-run-1-abc123") == "exec-run-1-abc123"

    with pytest.raises(PortError) as excinfo:
        validate_execution_id("geçersiz kimlik!")
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR

    with pytest.raises(PortError):
        validate_execution_id("   ")

    first = new_execution_id("run-1")
    second = new_execution_id("run-1")
    assert validate_execution_id(first) == first
    assert first != second  # benzersiz; ama bir kez atılınca zincirde SABİT


def test_save_checkpoint_binds_execution_run_and_revision(tmp_path) -> None:
    """Zarflı yazım: yürütme kimliği, run ve revizyon bağlamı zarfa işlenir."""
    store = FileCheckpointStore(tmp_path)
    state = make_state()
    payload = serialize_state(state)

    envelope = run(
        save_checkpoint(
            store,
            run_id="run-a8",
            execution_id="exec-zincir-1",
            kind=CheckpointKind.STATE,
            payload=payload,
            state_schema_version=STATE_SCHEMA_VERSION,
            context=state["context"],
        )
    )

    assert envelope.checkpoint_id == "state:exec-zincir-1"
    assert envelope.execution_id == "exec-zincir-1"
    assert envelope.run_id == "run-a8"
    # Makalesiz bağlam: revizyon bağlam alanları boş kalır.
    assert envelope.article_id is None
    assert envelope.article_revision is None

    loaded_envelope, loaded_payload = run(load_resume_payload(store, "run-a8"))
    assert loaded_envelope is not None
    assert loaded_envelope.execution_id == "exec-zincir-1"
    assert loaded_payload == payload


def test_save_checkpoint_refuses_unsupported_state_schema(tmp_path) -> None:
    """Uyumsuz state şema sürümü YAZILMAZ: zarfın doğması yazım anında engellenir."""
    store = FileCheckpointStore(tmp_path)
    with pytest.raises(PortError) as excinfo:
        run(
            save_checkpoint(
                store,
                run_id="run-a8",
                execution_id="exec-x",
                kind=CheckpointKind.STATE,
                payload=b"{}",
                state_schema_version=999,
            )
        )
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "999" in excinfo.value.message


def test_future_envelope_version_rejected_with_clear_message(tmp_path) -> None:
    """Uyumsuz (gelecek) zarf sürümü ANLAŞILIR sonuçla reddedilir (plan A8)."""
    store = FileCheckpointStore(tmp_path)
    future = CheckpointEnvelope(
        checkpoint_id="state:exec-future",
        run_id="run-a8",
        execution_id="exec-future",
        kind=CheckpointKind.STATE,
        state_schema_version=STATE_SCHEMA_VERSION,
        payload_b64="e30=",  # b"{}"
        saved_at=NOW,
        schema_version=999,
    )
    run(store.save("run-a8", future.checkpoint_id, future.model_dump_json().encode("utf-8")))

    with pytest.raises(PortError) as excinfo:
        run(load_resume_payload(store, "run-a8"))
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    message = excinfo.value.message
    assert "v999" in message and f"v{CHECKPOINT_SCHEMA_VERSION}" in message


def test_state_schema_version_mismatch_rejected_on_load(tmp_path) -> None:
    """Eski/uyumsuz state şeması yüklemede anlaşılır hatayla reddedilir."""
    store = FileCheckpointStore(tmp_path)
    envelope = CheckpointEnvelope(
        checkpoint_id="state:exec-old",
        run_id="run-a8",
        execution_id="exec-old",
        kind=CheckpointKind.STATE,
        state_schema_version=STATE_SCHEMA_VERSION - 1 if STATE_SCHEMA_VERSION > 1 else 999,
        payload_b64="e30=",
        saved_at=NOW,
    )
    run(store.save("run-a8", envelope.checkpoint_id, envelope.model_dump_json().encode("utf-8")))

    with pytest.raises(PortError) as excinfo:
        run(load_resume_payload(store, "run-a8"))
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "state şema sürümü" in excinfo.value.message


def test_load_resume_payload_passes_through_legacy_raw_payload(tmp_path) -> None:
    """Zarfsız (A1 dönemi ham PreparedRun JSON) payload geriye dönük uyumla döner."""
    store = FileCheckpointStore(tmp_path)
    raw = b'{"context": {}, "route": {}}'  # zarf değil; PreparedRun çözümlemesi resume'da
    run(store.save("run-1", "prepared:run", raw))

    envelope, payload = run(load_resume_payload(store, "run-1"))
    assert envelope is None
    assert payload == raw


def test_state_schema_rejects_tampered_version_in_payload() -> None:
    """ESKİ STATE ŞEMASI senaryosu: payload'daki sürüm oynanırsa anlaşılır hata döner."""
    payload = serialize_state(make_state())
    tampered = payload.replace(b'"schema_version": 1', b'"schema_version": 999')

    with pytest.raises(PortError) as excinfo:
        deserialize_state(tampered, expected_run_id="run-a8")
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
    assert "şema sürümü" in excinfo.value.message
    assert "999" in excinfo.value.message


def test_corrupt_envelope_body_reported_clearly() -> None:
    """Zarf gövdesi (base64) bozuksa anlaşılır validation_error döner."""
    envelope = CheckpointEnvelope(
        checkpoint_id="state:exec-bad",
        run_id="run-a8",
        execution_id="exec-bad",
        kind=CheckpointKind.STATE,
        payload_b64="!!!base64-degil!!!",
        saved_at=NOW,
    )
    with pytest.raises(PortError) as excinfo:
        envelope.payload_bytes()
    assert excinfo.value.code is AgentErrorCode.VALIDATION_ERROR
