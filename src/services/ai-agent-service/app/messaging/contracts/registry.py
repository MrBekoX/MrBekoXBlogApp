"""Mesaj türü kaydı: (sözleşme sürümü, mesaj türü) → yön, exchange/routing, payload modeli.

Değerler planın B1 yön/routing tablosundan (02-rabbitmq-haberlesme-plani.md:219-233)
alınmıştır; her sürümün ``src/contracts/agent/v{N}/contract.json`` dosyasıyla
denkliği ``tests/test_messaging_contracts_rules.py`` içinde doğrulanır.
Routing kuralı: ``routing_key = message_type + '.v{N}'``.

Sürümleme (karar kaydı K3/K4): kayıt ``(schema_version, message_type)``
anahtarlıdır; desteklenen sürümler ``SUPPORTED_SCHEMA_VERSIONS``'dır. v1 kaydı
DONMUŞTUR (18 tür). v2 kaydı v1'in run kapsamlı 13 türünden TÜRETİLİR (aynı
yön/exchange/üretici kuralları, ``.v2`` routing key ve v2 payload modelleri);
``content.*`` türleri yalnız v1'dedir. Tek bir global "aktif sürüm" yoktur: her
run mesajı run'ın kabul anında belirlenen wire sürümüyle
(``agent.jobs.wire_version``) kurulur. ``SCHEMA_VERSION`` ve
``MESSAGE_TYPE_REGISTRY`` adları yalnız v1 için geriye dönük takma addır; üretici
kodu sürümü run'dan alır.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Type

from pydantic import BaseModel

from .enums import Direction, Producer
from .payloads import (
    AgentActionProposedV1,
    AgentActionResultV1,
    AgentCancellationRequestedV1,
    AgentExecutionRequestedV1,
    AgentRunAcceptedV1,
    AgentRunCancelledV1,
    AgentRunCompletedV1,
    AgentRunFailedV1,
    AgentRunModeSelectedV1,
    AgentRunNeedsInputV1,
    AgentRunPartiallyCompletedV1,
    AgentRunProgressedV1,
    AgentResumeRequestedV1,
    ArticleContentChangedV1,
    ContentSnapshotBatchV1,
    ContentSnapshotCompletedV1,
    ProfileContentChangedV1,
    ProjectContentChangedV1,
)
from .payloads_v2 import (
    AgentActionProposedV2,
    AgentActionResultV2,
    AgentCancellationRequestedV2,
    AgentExecutionRequestedV2,
    AgentResumeRequestedV2,
    AgentRunAcceptedV2,
    AgentRunCancelledV2,
    AgentRunCompletedV2,
    AgentRunFailedV2,
    AgentRunModeSelectedV2,
    AgentRunNeedsInputV2,
    AgentRunPartiallyCompletedV2,
    AgentRunProgressedV2,
)

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "SCHEMA_VERSION",
    "WIRE_VERSION_V1",
    "WIRE_VERSION_V2",
    "SUPPORTED_SCHEMA_VERSIONS",
    "MESSAGE_TYPE_REGISTRY",
    "MESSAGE_TYPE_REGISTRY_V1",
    "MESSAGE_TYPE_REGISTRY_V2",
    "MESSAGE_TYPE_REGISTRIES",
    "MessageTypeSpec",
    "UnknownMessageSpec",
    "lookup_spec",
    "registry_for",
    "spec_for",
]

#: Komut/olay gövdesi üst sınırı: 256 KiB (B0 K7, plan satır 235: içerik gömülmez).
MAX_PAYLOAD_BYTES = 262_144

#: Donmuş ilk sözleşme sürümü (article/web kaynakları; konu kavramı yok).
WIRE_VERSION_V1 = 1
#: Who am I sürümü: konu, etkin niyet, profil snapshot'ı ve profile kaynak türü.
WIRE_VERSION_V2 = 2

#: Doğrulayıcının kabul ettiği sözleşme major sürümleri (artan sırada).
SUPPORTED_SCHEMA_VERSIONS: tuple[int, ...] = (WIRE_VERSION_V1, WIRE_VERSION_V2)

#: GERİYE DÖNÜK TAKMA AD (yalnız v1): v1 zarfı kuran eski testler/araçlar içindir.
#: Üretici kodu bu sabiti KULLANMAZ; sürüm run'ın ``wire_version`` değeridir.
SCHEMA_VERSION = WIRE_VERSION_V1

_COMMANDS = "blog.agent.commands"
_EVENTS = "blog.agent.events"
_CONTENT = "blog.content.events"

_BACKEND_PRODUCERS = (Producer.BACKEND_NET, Producer.TEST_EXECUTOR)
_AGENT_PRODUCERS = (Producer.AGENT_PY, Producer.TEST_EXECUTOR)


@dataclass(frozen=True)
class MessageTypeSpec:
    """Bir mesaj türünün sözleşme kaydı (contract.json girişinin kod karşılığı)."""

    message_type: str
    direction: Direction
    exchange: str
    routing_key: str
    allowed_producers: tuple[Producer, ...]
    requires_run_identity: bool
    requires_deadline: bool
    payload_schema: str
    payload_model: Type[BaseModel]
    #: Kaydın ait olduğu sözleşme major sürümü (zarf ``schema_version``).
    schema_version: int = WIRE_VERSION_V1


class UnknownMessageSpec(KeyError):
    """(sürüm, tür) çifti sözleşmede kayıtlı değil: sözleşme dışı mesaj üretilmez."""


MESSAGE_TYPE_REGISTRY_V1: dict[str, MessageTypeSpec] = {
    spec.message_type: spec
    for spec in (
        MessageTypeSpec(
            message_type="agent.execute.requested",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_COMMANDS,
            routing_key="agent.execute.requested.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=True,
            payload_schema="payloads/agent.execute.requested.schema.json",
            payload_model=AgentExecutionRequestedV1,
        ),
        MessageTypeSpec(
            message_type="agent.cancel.requested",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_COMMANDS,
            routing_key="agent.cancel.requested.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.cancel.requested.schema.json",
            payload_model=AgentCancellationRequestedV1,
        ),
        MessageTypeSpec(
            message_type="agent.resume.requested",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_COMMANDS,
            routing_key="agent.resume.requested.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.resume.requested.schema.json",
            payload_model=AgentResumeRequestedV1,
        ),
        MessageTypeSpec(
            message_type="agent.action.result",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_COMMANDS,
            routing_key="agent.action.result.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.action.result.schema.json",
            payload_model=AgentActionResultV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.accepted",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.accepted.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.accepted.schema.json",
            payload_model=AgentRunAcceptedV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.mode_selected",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.mode_selected.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.mode_selected.schema.json",
            payload_model=AgentRunModeSelectedV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.progressed",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.progressed.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.progressed.schema.json",
            payload_model=AgentRunProgressedV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.needs_input",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.needs_input.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.needs_input.schema.json",
            payload_model=AgentRunNeedsInputV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.completed",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.completed.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.completed.schema.json",
            payload_model=AgentRunCompletedV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.partially_completed",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.partially_completed.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.partially_completed.schema.json",
            payload_model=AgentRunPartiallyCompletedV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.failed",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.failed.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.failed.schema.json",
            payload_model=AgentRunFailedV1,
        ),
        MessageTypeSpec(
            message_type="agent.run.cancelled",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.run.cancelled.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.run.cancelled.schema.json",
            payload_model=AgentRunCancelledV1,
        ),
        MessageTypeSpec(
            message_type="agent.action.proposed",
            direction=Direction.AGENT_TO_BACKEND,
            exchange=_EVENTS,
            routing_key="agent.action.proposed.v1",
            allowed_producers=_AGENT_PRODUCERS,
            requires_run_identity=True,
            requires_deadline=False,
            payload_schema="payloads/agent.action.proposed.schema.json",
            payload_model=AgentActionProposedV1,
        ),
        MessageTypeSpec(
            message_type="content.article.changed",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_CONTENT,
            routing_key="content.article.changed.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=False,
            requires_deadline=False,
            payload_schema="payloads/content.article.changed.schema.json",
            payload_model=ArticleContentChangedV1,
        ),
        MessageTypeSpec(
            message_type="content.sync.batch",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_CONTENT,
            routing_key="content.sync.batch.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=False,
            requires_deadline=False,
            payload_schema="payloads/content.sync.batch.schema.json",
            payload_model=ContentSnapshotBatchV1,
        ),
        MessageTypeSpec(
            message_type="content.sync.completed",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_CONTENT,
            routing_key="content.sync.completed.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=False,
            requires_deadline=False,
            payload_schema="payloads/content.sync.completed.schema.json",
            payload_model=ContentSnapshotCompletedV1,
        ),
        MessageTypeSpec(
            message_type="content.profile.changed",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_CONTENT,
            routing_key="content.profile.changed.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=False,
            requires_deadline=False,
            payload_schema="payloads/content.profile.changed.schema.json",
            payload_model=ProfileContentChangedV1,
        ),
        MessageTypeSpec(
            message_type="content.project.changed",
            direction=Direction.BACKEND_TO_AGENT,
            exchange=_CONTENT,
            routing_key="content.project.changed.v1",
            allowed_producers=_BACKEND_PRODUCERS,
            requires_run_identity=False,
            requires_deadline=False,
            payload_schema="payloads/content.project.changed.schema.json",
            payload_model=ProjectContentChangedV1,
        ),
    )
}


#: v1 kaydının geriye dönük adı (donmuş 18 tür).
MESSAGE_TYPE_REGISTRY = MESSAGE_TYPE_REGISTRY_V1

#: v2 payload modelleri: run kapsamlı 13 tür (content.* yalnız v1).
_V2_PAYLOAD_MODELS: dict[str, Type[BaseModel]] = {
    "agent.execute.requested": AgentExecutionRequestedV2,
    "agent.cancel.requested": AgentCancellationRequestedV2,
    "agent.resume.requested": AgentResumeRequestedV2,
    "agent.action.result": AgentActionResultV2,
    "agent.run.accepted": AgentRunAcceptedV2,
    "agent.run.mode_selected": AgentRunModeSelectedV2,
    "agent.run.progressed": AgentRunProgressedV2,
    "agent.run.needs_input": AgentRunNeedsInputV2,
    "agent.run.completed": AgentRunCompletedV2,
    "agent.run.partially_completed": AgentRunPartiallyCompletedV2,
    "agent.run.failed": AgentRunFailedV2,
    "agent.run.cancelled": AgentRunCancelledV2,
    "agent.action.proposed": AgentActionProposedV2,
}


def _derive_v2(v1: dict[str, MessageTypeSpec]) -> dict[str, MessageTypeSpec]:
    """v2 kaydını v1'den türetir: yalnız run kapsamlı türler, ``.v2`` routing, v2 modelleri.

    Yön/exchange/üretici/run kimliği/deadline kuralları v1 ile birebir aynıdır
    (``_generate_v2.py`` ``build_contract`` ile aynı türetme; denklik
    ``v2/contract.json`` testinde sabit).
    """

    derived: dict[str, MessageTypeSpec] = {}
    for name, spec in v1.items():
        if not spec.requires_run_identity:
            continue  # content.* türleri run sürümünden bağımsızdır; v1'de kalır
        derived[name] = replace(
            spec,
            routing_key=f"{name}.v{WIRE_VERSION_V2}",
            payload_model=_V2_PAYLOAD_MODELS[name],
            schema_version=WIRE_VERSION_V2,
        )
    if set(derived) != set(_V2_PAYLOAD_MODELS):
        raise RuntimeError("v2 kaydı v1'in run kapsamlı türleriyle eşleşmiyor")
    return derived


MESSAGE_TYPE_REGISTRY_V2: dict[str, MessageTypeSpec] = _derive_v2(MESSAGE_TYPE_REGISTRY_V1)

#: sürüm → (tür → kayıt). Doğrulayıcı önce sürümü, sonra türü seçer.
MESSAGE_TYPE_REGISTRIES: dict[int, dict[str, MessageTypeSpec]] = {
    WIRE_VERSION_V1: MESSAGE_TYPE_REGISTRY_V1,
    WIRE_VERSION_V2: MESSAGE_TYPE_REGISTRY_V2,
}


def registry_for(schema_version: int) -> dict[str, MessageTypeSpec]:
    """Sürümün tür kaydı; desteklenmeyen sürüm ``UnknownMessageSpec``."""

    registry = MESSAGE_TYPE_REGISTRIES.get(schema_version)
    if registry is None:
        raise UnknownMessageSpec(f"desteklenmeyen sözleşme sürümü: {schema_version}")
    return registry


def lookup_spec(schema_version: int, message_type: str) -> MessageTypeSpec | None:
    """(sürüm, tür) kaydı; yoksa ``None`` (doğrulayıcı kategorize eder)."""

    registry = MESSAGE_TYPE_REGISTRIES.get(schema_version)
    if registry is None:
        return None
    return registry.get(message_type)


def spec_for(schema_version: int, message_type: str) -> MessageTypeSpec:
    """Üretici yolu: (sürüm, tür) kaydı zorunludur; yoksa ``UnknownMessageSpec``."""

    spec = lookup_spec(schema_version, message_type)
    if spec is None:
        raise UnknownMessageSpec(
            f"sözleşmede kayıtlı değil: schema_version={schema_version} message_type={message_type}"
        )
    return spec
