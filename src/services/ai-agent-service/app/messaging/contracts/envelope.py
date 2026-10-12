"""B1 zarf modeli (plan satır 183-196 tablosu + delivery_attempt uzantısı).

Zorunlu alanlar: message_id, message_type, schema_version, correlation_id,
occurred_at, producer, payload. Opsiyonel alanlarda null taşınmaz; alan çıkarılır
(``TransportModel._reject_explicit_nulls``). delivery_attempt transport tekrar
yayını sayacıdır; agent yürütme denemesi payload'taki execution_attempt'tir.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .enums import Producer
from .formats import StrictInt, TraceParent, UtcIsoString, UuidString
from .payloads import TransportModel

__all__ = ["AgentEnvelope"]


class AgentEnvelope(TransportModel):
    """Komut/olay zarfı; AMQP message_id/correlation_id/content_type bu alanlarla tutarlı set edilir."""

    message_id: UuidString
    message_type: str = Field(min_length=1, max_length=64)
    schema_version: StrictInt
    run_id: UuidString | None = None
    conversation_id: UuidString | None = None
    correlation_id: UuidString
    causation_id: UuidString | None = None
    occurred_at: UtcIsoString
    deadline_at: UtcIsoString | None = None
    producer: Producer
    trace_context: TraceParent | None = None
    delivery_attempt: StrictInt = Field(default=0, ge=0)
    payload: dict[str, Any]
