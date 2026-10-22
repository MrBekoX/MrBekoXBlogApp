"""K4/K5 offline: worker'ın v1/v2 run yürütmesi, profil sınırları ve terminal sözleşmesi.

Çekirdek giriş noktaları (``prepare_and_route``/``execute_plan``) worker modülünde
yerine geçen kayıtçılarla değiştirilir: kanıtlanan WORKER yarısıdır — bağlam
kurma, işin sürümüyle DTO seçimi, ``profile_knowledge``/web araç portu kararı,
v2 ``mode_selected``, sink'te delta düşürme + ilerleme temizliği, kaynak
denetimi ve run sürümüyle terminal zarf. Gerçek çekirdek + gerçek DB/broker
zinciri DB'li paketlerde ve PY-CORE profil testlerinde ayrıca sınanır.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_core.checkpoint.store import FileCheckpointStore
from agent_core.entrypoints import PreparedRun
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import (
    AgentMode,
    AgentOutcome,
    BudgetProfile,
    ConversationTopic,
    DomainProgress,
    ProfileSnapshotRef,
    ProgressKind,
    RouteDecision,
    RunIntent,
    RunStatus,
    SourceReference,
    SourceScope,
    UsageRecord,
)
from agent_core.adapters.test_doubles import FakeModelProvider
import messaging.worker as worker_module
from messaging.worker import (
    ExecutionDependencies,
    ExecutionWorker,
    WorkerSettings,
    _WorkerProgressSink,
    audit_profile_outcome,
    is_profile_bound,
    planned_source_scope,
)

from .fakes import (
    PROFILE_HASH,
    FakeWatch,
    RecordingEventPublisher,
    RecordingJobStore,
    assert_valid_wire,
    claimed_job,
    execute_envelope,
)

NOW = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)
SNAPSHOT = ProfileSnapshotRef(profile_id="sample-author", revision=1, content_hash=PROFILE_HASH)
OTHER_SNAPSHOT = ProfileSnapshotRef(profile_id="sample-author", revision=2, content_hash="0" * 64)

WHO_AM_I = "valid/agent.execute.requested.who_am_i.json"
AUTO_WITH_SNAPSHOT = "valid/agent.execute.requested.auto_with_profile_snapshot.json"
V2_ARTICLE = "valid/agent.execute.requested.with_article.json"
V1_PLAIN = "valid/agent.execute.requested.json"

WEB_TOOLS_SENTINEL = {"search": object()}
PROFILE_KNOWLEDGE_SENTINEL = object()
LEGACY_PROFILE_SENTINEL = object()


def _citation(snapshot: ProfileSnapshotRef = SNAPSHOT, section: str = "education") -> SourceReference:
    return SourceReference(
        kind="profile",
        title="Eğitim",
        profile_id=snapshot.profile_id,
        profile_revision=snapshot.revision,
        profile_content_hash=snapshot.content_hash,
        section_id=section,
        chunk_index=0,
    )


def _usage(run_id: str) -> UsageRecord:
    return UsageRecord(run_id=run_id, model_calls=1, total_tokens=12, recorded_at=NOW)


def _profile_outcome(run_id: str, **overrides: Any) -> AgentOutcome:
    defaults: dict[str, Any] = dict(
        selected_mode=AgentMode.FAST,
        status=RunStatus.COMPLETED,
        answer="Sample Author, Demo University'nde Bilgisayar Mühendisliği okudu.",
        citations=[_citation()],
        source_scope=SourceScope.PROFILE,
        usage=_usage(run_id),
        run_intent=RunIntent.PROFILE,
        profile_snapshot=SNAPSHOT,
    )
    defaults.update(overrides)
    return AgentOutcome(**defaults)


class _Core:
    """``prepare_and_route``/``execute_plan`` kayıtçısı: rota ve sonuç test başına verilir."""

    def __init__(self, intent: RunIntent, outcome_factory, *, emit: list[DomainProgress] | None = None,
                 selected_mode: AgentMode = AgentMode.FAST, needs_web: bool = False) -> None:
        self.intent = intent
        self.outcome_factory = outcome_factory
        self.emit = emit or []
        self.selected_mode = selected_mode
        self.needs_web = needs_web
        self.execute_kwargs: dict[str, Any] | None = None
        self.prepared: PreparedRun | None = None

    async def prepare_and_route(self, context, **kwargs: Any) -> PreparedRun:
        route = RouteDecision(
            run_id=context.run_id,
            selected_mode=self.selected_mode,
            intent=self.intent,
            needs_web=self.needs_web,
            brief_reason="router gerekçesi: kullanıcı sorusu metni burada",
            decided_at=NOW,
        )
        self.prepared = PreparedRun(context=context, route=route, prepared_at=NOW, execution_id=kwargs.get("execution_id"))
        return self.prepared

    async def execute_plan(self, prepared: PreparedRun, **kwargs: Any) -> AgentOutcome:
        self.execute_kwargs = kwargs
        progress = kwargs["progress"]
        for event in self.emit:
            await progress.publish(event)
        return self.outcome_factory(prepared.context.run_id)


def _progress(run_id: str, kind: ProgressKind, message: str, detail: dict[str, str] | None = None) -> DomainProgress:
    return DomainProgress(run_id=run_id, kind=kind, message=message, detail=detail or {}, occurred_at=NOW)


def _run(monkeypatch, tmp_path, core: _Core, fixture: str, *, version: int, payload: dict | None = None):
    monkeypatch.setattr(worker_module, "prepare_and_route", core.prepare_and_route)
    monkeypatch.setattr(worker_module, "execute_plan", core.execute_plan)
    store = RecordingJobStore()
    publisher = RecordingEventPublisher()
    deps = ExecutionDependencies(
        model=FakeModelProvider("kullanılmaz"),
        web_tools=WEB_TOOLS_SENTINEL,
        profile_knowledge=PROFILE_KNOWLEDGE_SENTINEL,
        profile_repository=LEGACY_PROFILE_SENTINEL,
    )
    worker = ExecutionWorker(
        store,  # type: ignore[arg-type]
        deps,
        settings=WorkerSettings(worker_id="offline-worker", lease_seconds=60.0),
        publisher=publisher,  # type: ignore[arg-type]
        checkpoint_store=FileCheckpointStore(tmp_path / "checkpoints"),
    )
    claimed = claimed_job(execute_envelope(fixture, version=version), wire_version=version, payload=payload)
    result = asyncio.run(worker.execute_claimed(claimed))
    return result, store, publisher, claimed


def _terminal(store: RecordingJobStore) -> tuple[str, Any]:
    if store.completed:
        (_, envelope), = store.completed
        return "completed", envelope
    (_, envelope), = store.failed
    return "failed", envelope


# --- açık who_am_i (v2) ---


def test_who_am_i_run_is_profile_bound_end_to_end(monkeypatch, tmp_path) -> None:
    core = _Core(
        RunIntent.PROFILE,
        _profile_outcome,
        emit=[
            DomainProgress(run_id="x", kind=ProgressKind.GENERATION_DELTA, message="Sample Author", occurred_at=NOW),
            DomainProgress(
                run_id="x",
                kind=ProgressKind.RETRIEVAL_COMPLETED,
                message="Eğitim bölümünde: Demo University",
                detail={"hits": "3", "snippet": "Bilgisayar Mühendisliği"},
                occurred_at=NOW,
            ),
        ],
    )

    result, store, publisher, claimed = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "completed", result.detail
    # Bağlam: v2 konu + pinlenmiş snapshot; makale bağlamı yok.
    context = core.prepared.context
    assert context.conversation_topic is ConversationTopic.WHO_AM_I
    assert context.profile_snapshot.same_as(SNAPSHOT)
    assert context.article_id is None and context.selected_text is None
    # Port düzeyi: web araçları HİÇ verilmez; profil depoları aktarılır.
    assert core.execute_kwargs["web_tools"] is None
    assert core.execute_kwargs["profile_knowledge"] is PROFILE_KNOWLEDGE_SENTINEL
    assert core.execute_kwargs["profile_repository"] is LEGACY_PROFILE_SENTINEL
    # Ara olaylar: delta yayınlanmaz; ilerleme sabit metin + yalnız sayaç.
    assert publisher.deltas == []
    (progress,) = publisher.progressed
    assert progress["message"] == "Profil kaynakları bulundu"
    assert progress["detail"] == {"hits": "3"}
    # v2 mode_selected: etkin niyet/kapsam/snapshot; web yok; gerekçe sabit metin.
    (mode,) = publisher.mode_selected
    assert mode["run_intent"] == "profile" and mode["source_scope"] == "profile"
    assert mode["requires_web_search"] is False
    assert mode["profile_snapshot"].same_as(SNAPSHOT)
    assert "kullanıcı sorusu" not in mode["reason"]
    # Terminal: v2 sözleşmesinde, run_intent + snapshot + profile citation.
    kind, envelope = _terminal(store)
    assert kind == "completed" and envelope.schema_version == 2
    parsed = assert_valid_wire(envelope.model_dump(mode="json", exclude_none=True))
    assert parsed.spec.routing_key == "agent.run.completed.v2"
    assert parsed.payload.run_intent.value == "profile"
    assert parsed.payload.profile_snapshot.content_hash == PROFILE_HASH
    assert parsed.payload.citations[0].url == "/about#education"
    result_json = store.completed[0][0]
    assert result_json["wire_version"] == 2 and result_json["run_intent"] == "profile"


def test_profile_refusal_without_citations_carries_pinned_snapshot(monkeypatch, tmp_path) -> None:
    core = _Core(
        RunIntent.PROFILE,
        lambda run_id: _profile_outcome(
            run_id, answer="Bu bilgi paylaşılmıyor.", citations=[], profile_snapshot=None
        ),
    )

    result, store, _publisher, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "completed", result.detail
    _, envelope = _terminal(store)
    parsed = assert_valid_wire(envelope.model_dump(mode="json", exclude_none=True))
    assert parsed.payload.citations == []
    assert parsed.payload.profile_snapshot.content_hash == PROFILE_HASH  # pinlenmiş sürüm


def test_who_am_i_resolved_to_non_profile_intent_fails_validation(monkeypatch, tmp_path) -> None:
    core = _Core(
        RunIntent.GENERAL,
        lambda run_id: _profile_outcome(
            run_id, citations=[], source_scope=SourceScope.GENERAL, run_intent=RunIntent.GENERAL, profile_snapshot=None
        ),
    )

    result, store, publisher, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "failed"
    kind, envelope = _terminal(store)
    assert kind == "failed" and envelope.schema_version == 2
    assert envelope.payload["error_code"] == "validation_error"
    assert "who_am_i" in envelope.payload["error_message"]
    assert core.execute_kwargs["web_tools"] is None  # açık konu: koruma rota öncesi açık


@pytest.mark.parametrize(
    "factory",
    [
        lambda run_id: _profile_outcome(run_id, citations=[_citation(OTHER_SNAPSHOT)], profile_snapshot=OTHER_SNAPSHOT),
        lambda run_id: _profile_outcome(run_id, profile_snapshot=OTHER_SNAPSHOT, citations=[]),
    ],
    ids=["citation-other-revision", "result-other-revision"],
)
def test_profile_result_from_other_revision_fails_validation(monkeypatch, tmp_path, factory) -> None:
    core = _Core(RunIntent.PROFILE, factory)

    result, store, _, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "failed"
    _, envelope = _terminal(store)
    assert envelope.payload["error_code"] == "validation_error"
    assert envelope.payload["run_intent"] == "profile"
    assert envelope.payload["profile_snapshot"]["content_hash"] == PROFILE_HASH


def test_profile_run_needs_input_is_rejected(monkeypatch, tmp_path) -> None:
    core = _Core(
        RunIntent.PROFILE,
        lambda run_id: AgentOutcome(
            selected_mode=AgentMode.FAST,
            status=RunStatus.NEEDS_INPUT,
            source_scope=SourceScope.PROFILE,
            unresolved_questions=["Hangi bilgiyi istiyorsunuz?"],
            usage=_usage(run_id),
        ),
    )

    result, store, _, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "failed"
    assert store.requeued == []  # askıda iş oluşturulmadı
    _, envelope = _terminal(store)
    assert envelope.payload["error_code"] == "validation_error"


def test_profile_config_error_is_v2_failed_with_intent(monkeypatch, tmp_path) -> None:
    core = _Core(
        RunIntent.PROFILE,
        lambda run_id: AgentOutcome(
            selected_mode=AgentMode.FAST,
            status=RunStatus.FAILED,
            source_scope=SourceScope.PROFILE,
            usage=_usage(run_id),
            error_code=AgentErrorCode.CONFIG_ERROR,
            error_message="canonical profil kaynağı kullanılamıyor",
            run_intent=RunIntent.PROFILE,
            profile_snapshot=SNAPSHOT,
        ),
    )

    result, store, _, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "failed"
    _, envelope = _terminal(store)
    parsed = assert_valid_wire(envelope.model_dump(mode="json", exclude_none=True))
    assert parsed.spec.routing_key == "agent.run.failed.v2"
    assert parsed.payload.error_code.value == "config_error"
    assert parsed.payload.run_intent.value == "profile"


def test_who_am_i_deep_research_preference_is_not_deferred_to_research(monkeypatch, tmp_path) -> None:
    core = _Core(RunIntent.PROFILE, _profile_outcome, selected_mode=AgentMode.DEEP_RESEARCH)

    result, store, publisher, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "completed", result.detail
    assert store.requeued == []  # profil corpus'u: araştırma kapasitesine ertelenmez
    assert publisher.mode_selected[0]["requires_web_search"] is False
    assert core.execute_kwargs["web_tools"] is None


# --- AUTO (v2) ---


def test_auto_to_profile_enables_guard_after_routing(monkeypatch, tmp_path) -> None:
    core = _Core(
        RunIntent.PROFILE,
        _profile_outcome,
        emit=[DomainProgress(run_id="x", kind=ProgressKind.GENERATION_DELTA, message="taslak", occurred_at=NOW)],
    )

    result, store, publisher, _ = _run(monkeypatch, tmp_path, core, AUTO_WITH_SNAPSHOT, version=2)

    assert result.action == "completed", result.detail
    assert core.prepared.context.conversation_topic is ConversationTopic.AUTO
    assert publisher.deltas == []  # AUTO→PROFILE: delta yayınlanmaz
    assert core.execute_kwargs["web_tools"] is None
    assert publisher.mode_selected[0]["run_intent"] == "profile"


def test_auto_article_run_keeps_streaming_and_tools(monkeypatch, tmp_path) -> None:
    def outcome(run_id: str) -> AgentOutcome:
        return AgentOutcome(
            selected_mode=AgentMode.FAST,
            status=RunStatus.COMPLETED,
            answer="Makale CQRS'i anlatıyor.",
            citations=[SourceReference(kind="article", article_id="my-blog-post", article_revision=7, chunk_index=0)],
            source_scope=SourceScope.ARTICLE,
            usage=_usage(run_id),
            run_intent=RunIntent.ARTICLE_QA,
        )

    core = _Core(
        RunIntent.ARTICLE_QA,
        outcome,
        emit=[DomainProgress(run_id="x", kind=ProgressKind.GENERATION_DELTA, message="Makale", occurred_at=NOW)],
    )

    result, store, publisher, _ = _run(monkeypatch, tmp_path, core, V2_ARTICLE, version=2)

    assert result.action == "completed", result.detail
    assert len(publisher.deltas) == 1  # diğer konularda streaming korunur
    assert core.execute_kwargs["web_tools"] is WEB_TOOLS_SENTINEL
    (mode,) = publisher.mode_selected
    assert mode["run_intent"] == "article_qa" and mode["source_scope"] == "article"
    assert mode["profile_snapshot"] is None
    _, envelope = _terminal(store)
    parsed = assert_valid_wire(envelope.model_dump(mode="json", exclude_none=True))
    assert parsed.payload.run_intent.value == "article_qa"
    assert parsed.payload.citations[0].source_id == "article:my-blog-post:7:0"


# --- v1 (legacy) ---


def test_v1_run_keeps_v1_wire_and_no_mode_selected(monkeypatch, tmp_path) -> None:
    def outcome(run_id: str) -> AgentOutcome:
        return AgentOutcome(
            selected_mode=AgentMode.FAST,
            status=RunStatus.COMPLETED,
            answer="Genel cevap",
            source_scope=SourceScope.GENERAL,
            usage=_usage(run_id),
            run_intent=RunIntent.GENERAL,
        )

    core = _Core(RunIntent.GENERAL, outcome)

    result, store, publisher, _ = _run(monkeypatch, tmp_path, core, V1_PLAIN, version=1)

    assert result.action == "completed", result.detail
    assert core.prepared.context.conversation_topic is None  # v1: konu yok (legacy A9)
    assert publisher.mode_selected == []
    _, envelope = _terminal(store)
    parsed = assert_valid_wire(envelope.model_dump(mode="json", exclude_none=True))
    assert parsed.schema_version == 1 and parsed.spec.routing_key == "agent.run.completed.v1"
    assert "run_intent" not in envelope.payload


def test_v1_run_with_profile_citation_fails_validation_in_v1(monkeypatch, tmp_path) -> None:
    core = _Core(RunIntent.PROFILE, lambda run_id: _profile_outcome(run_id))

    result, store, _, _ = _run(monkeypatch, tmp_path, core, V1_PLAIN, version=1)

    assert result.action == "failed"
    _, envelope = _terminal(store)
    assert envelope.schema_version == 1
    assert envelope.payload["error_code"] == "validation_error"
    assert "run_intent" not in envelope.payload  # v1 failed v2 alanı taşımaz


def test_v1_legacy_profile_run_is_still_guarded_and_toolless(monkeypatch, tmp_path) -> None:
    def outcome(run_id: str) -> AgentOutcome:
        return AgentOutcome(
            selected_mode=AgentMode.FAST,
            status=RunStatus.COMPLETED,
            answer="Kısa tanıtım (legacy A9).",
            source_scope=SourceScope.PROFILE,
            usage=_usage(run_id),
            run_intent=RunIntent.PROFILE,
        )

    core = _Core(
        RunIntent.PROFILE,
        outcome,
        emit=[DomainProgress(run_id="x", kind=ProgressKind.GENERATION_DELTA, message="tanıtım", occurred_at=NOW)],
    )

    result, store, publisher, _ = _run(monkeypatch, tmp_path, core, V1_PLAIN, version=1)

    assert result.action == "completed", result.detail
    assert publisher.deltas == []
    assert core.execute_kwargs["web_tools"] is None
    assert core.execute_kwargs["profile_repository"] is LEGACY_PROFILE_SENTINEL  # A9 yolu açık
    _, envelope = _terminal(store)
    assert envelope.schema_version == 1


# --- payload/bağlam doğrulaması ---


def test_claimed_payload_is_revalidated_with_job_version(monkeypatch, tmp_path) -> None:
    v1_payload = execute_envelope(V1_PLAIN, version=1).payload
    core = _Core(RunIntent.GENERAL, _profile_outcome)

    # v2 işi v1 şekilli payload taşıyorsa (konu yok) yürütme başlamaz.
    result, store, _, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2, payload=v1_payload)

    assert result.action == "failed"
    assert core.prepared is None
    _, envelope = _terminal(store)
    assert envelope.schema_version == 2 and envelope.payload["error_code"] == "validation_error"


def test_v1_job_rejects_v2_payload_fields(monkeypatch, tmp_path) -> None:
    v2_payload = execute_envelope(WHO_AM_I, version=2).payload
    core = _Core(RunIntent.GENERAL, _profile_outcome)

    result, store, _, _ = _run(monkeypatch, tmp_path, core, V1_PLAIN, version=1, payload=v2_payload)

    assert result.action == "failed"
    _, envelope = _terminal(store)
    assert envelope.schema_version == 1 and envelope.payload["error_code"] == "validation_error"


def test_who_am_i_job_without_snapshot_fails_before_routing(monkeypatch, tmp_path) -> None:
    payload = dict(execute_envelope(WHO_AM_I, version=2).payload)
    payload.pop("profile_snapshot")
    core = _Core(RunIntent.PROFILE, _profile_outcome)

    result, store, _, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2, payload=payload)

    assert result.action == "failed" and core.prepared is None
    _, envelope = _terminal(store)
    assert "profile_snapshot" in envelope.payload["error_message"]


def test_who_am_i_context_zeroes_web_budget(tmp_path) -> None:
    worker = ExecutionWorker(
        RecordingJobStore(),  # type: ignore[arg-type]
        ExecutionDependencies(model=FakeModelProvider("x")),
        settings=WorkerSettings(
            worker_id="w",
            budget_profile=BudgetProfile(
                name="geniş", max_model_calls=4, max_total_tokens=1000, max_tool_calls=3,
                max_web_search_calls=2, max_duration_seconds=60.0,
            ),
        ),
        checkpoint_store=FileCheckpointStore(tmp_path),
    )
    who = claimed_job(execute_envelope(WHO_AM_I, version=2), wire_version=2)
    auto = claimed_job(execute_envelope(AUTO_WITH_SNAPSHOT, version=2), wire_version=2)

    who_context = worker._build_context(worker._validate_claimed_payload(who), who)
    auto_context = worker._build_context(worker._validate_claimed_payload(auto), auto)

    assert who_context.budget_profile.max_web_search_calls == 0
    assert who_context.budget_profile.max_tool_calls == 0
    assert auto_context.budget_profile.max_web_search_calls == 2  # AUTO: rota kararına kadar değişmez
    assert auto_context.conversation_topic is ConversationTopic.AUTO
    assert auto_context.profile_snapshot.same_as(SNAPSHOT)


# --- sink + denetim birimleri ---


def _sink(publisher: RecordingEventPublisher, *, guard: bool) -> _WorkerProgressSink:
    return _WorkerProgressSink(
        run_id="aaaaaaa1-0000-4000-8000-000000000001",
        conversation_id="bbbbbbb1-0000-4000-8000-000000000002",
        correlation_id="ccccccc1-0000-4000-8000-000000000003",
        causation_id="ddddddd1-0000-4000-8000-000000000004",
        execution_attempt=1,
        publisher=publisher,  # type: ignore[arg-type]
        watch=FakeWatch(),  # type: ignore[arg-type]
        profile_guard=guard,
    )


def test_sink_profile_guard_drops_deltas_and_sanitizes_progress() -> None:
    publisher = RecordingEventPublisher()
    sink = _sink(publisher, guard=True)

    asyncio.run(sink.publish(_progress("r", ProgressKind.GENERATION_DELTA, "Sample 2020'de")))
    asyncio.run(sink.publish(_progress("r", ProgressKind.GENERATION_STARTED, "Cevap: Sample ...", {"chars": "12", "draft": "Sample"})))
    asyncio.run(sink.publish(_progress("r", ProgressKind.RESEARCH_STARTED, "web: Sample")))

    assert publisher.deltas == [] and sink.dropped_deltas == 1
    assert [p["message"] for p in publisher.progressed] == ["Yanıt hazırlanıyor", "Profil yanıtı hazırlanıyor"]
    assert publisher.progressed[0]["detail"] == {"chars": "12"}


def test_sink_without_guard_keeps_behavior_and_guard_is_one_way() -> None:
    publisher = RecordingEventPublisher()
    sink = _sink(publisher, guard=False)

    asyncio.run(sink.publish(_progress("r", ProgressKind.GENERATION_DELTA, "Makale")))
    asyncio.run(sink.publish(_progress("r", ProgressKind.GENERATION_STARTED, "yanıt üretiliyor", {"note": "serbest"})))
    sink.enable_profile_guard()
    asyncio.run(sink.publish(_progress("r", ProgressKind.GENERATION_DELTA, "sızmamalı")))

    assert [d["text"] for d in publisher.deltas] == ["Makale"]
    assert publisher.progressed[0]["message"] == "yanıt üretiliyor"
    assert publisher.progressed[0]["detail"] == {"note": "serbest"}
    assert sink.profile_guard is True


def test_planned_scope_and_profile_binding() -> None:
    who = claimed_job(execute_envelope(WHO_AM_I, version=2), wire_version=2)
    worker = ExecutionWorker(
        RecordingJobStore(),  # type: ignore[arg-type]
        ExecutionDependencies(model=FakeModelProvider("x")),
        settings=WorkerSettings(worker_id="w"),
        checkpoint_store=FileCheckpointStore("unused-dir-not-created"),
    )
    context = worker._build_context(worker._validate_claimed_payload(who), who)
    route = RouteDecision(run_id=context.run_id, selected_mode=AgentMode.FAST, intent=RunIntent.PROFILE,
                          brief_reason="profil", decided_at=NOW)
    prepared = PreparedRun(context=context, route=route, prepared_at=NOW)

    assert planned_source_scope(prepared) is SourceScope.PROFILE
    assert is_profile_bound(context, None) is True  # açık konu rota öncesi bağlar
    assert is_profile_bound(context.model_copy(update={"conversation_topic": ConversationTopic.AUTO}), RunIntent.GENERAL) is False


@pytest.mark.parametrize(
    ("version", "topic", "intent", "outcome_kwargs", "expected"),
    [
        (2, ConversationTopic.WHO_AM_I, RunIntent.PROFILE, {}, None),
        (2, ConversationTopic.WHO_AM_I, RunIntent.GENERAL,
         {"citations": [], "source_scope": SourceScope.GENERAL, "profile_snapshot": None, "run_intent": RunIntent.GENERAL},
         "who_am_i"),
        (2, ConversationTopic.AUTO, RunIntent.PROFILE,
         {"citations": [_citation(OTHER_SNAPSHOT)], "profile_snapshot": OTHER_SNAPSHOT}, "pinlenmiş"),
        (1, None, RunIntent.PROFILE, {}, "v1"),
    ],
    ids=["ok", "who-am-i-non-profile", "other-revision", "v1-profile-citation"],
)
def test_audit_profile_outcome_rules(version, topic, intent, outcome_kwargs, expected) -> None:
    from agent_core.models import BudgetProfile, ExecutionContext

    context = ExecutionContext(
        run_id="r1",
        conversation_id="c1",
        question="Sample nerede okudu?",
        language="tr",
        budget_profile=BudgetProfile(name="b", max_model_calls=1, max_total_tokens=10, max_duration_seconds=1.0),
        conversation_topic=topic,
        profile_snapshot=SNAPSHOT if topic is not None else None,
    )
    outcome = _profile_outcome("r1", **outcome_kwargs)

    violation = audit_profile_outcome(wire_version=version, context=context, run_intent=intent, outcome=outcome)

    if expected is None:
        assert violation is None
    else:
        assert violation is not None and expected in violation


def test_port_error_from_core_is_v2_failed(monkeypatch, tmp_path) -> None:
    class _Failing(_Core):
        async def execute_plan(self, prepared, **kwargs):
            raise PortError(AgentErrorCode.TIMEOUT, "süre doldu", port="test")

    core = _Failing(RunIntent.PROFILE, _profile_outcome)

    result, store, _, _ = _run(monkeypatch, tmp_path, core, WHO_AM_I, version=2)

    assert result.action == "failed"
    _, envelope = _terminal(store)
    assert envelope.schema_version == 2 and envelope.payload["error_code"] == "timeout"
