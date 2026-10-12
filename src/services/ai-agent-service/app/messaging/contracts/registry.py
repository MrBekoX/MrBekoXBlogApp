"""Mesaj türü kaydı: yön, exchange/routing eşlemesi ve payload modeli.

Değerler planın B1 yön/routing tablosundan (02-rabbitmq-haberlesme-plani.md:219-233)
alınmıştır; contract.json ile denklik ``tests/test_messaging_contracts_rules.py``
içinde doğrulanır. Routing kuralı: ``routing_key = message_type + '.v1'``.
"""

from __future__ import annotations

from dataclasses import dataclass
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

__all__ = ["MAX_PAYLOAD_BYTES", "SCHEMA_VERSION", "MESSAGE_TYPE_REGISTRY", "MessageTypeSpec"]

#: Komut/olay gövdesi üst sınırı: 256 KiB (B0 K7, plan satır 235: içerik gömülmez).
MAX_PAYLOAD_BYTES = 262_144

#: Kabul edilen tek sözleşme major sürümü.
SCHEMA_VERSION = 1

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


MESSAGE_TYPE_REGISTRY: dict[str, MessageTypeSpec] = {
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
