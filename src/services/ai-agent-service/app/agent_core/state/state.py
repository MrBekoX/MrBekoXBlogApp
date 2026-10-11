"""Ortak LangGraph state (plan A2, ``01-agent-gelistirme-plani.md:205``).

Alan kümesi planın listesidir: konuşma mesajları, router kararı, içerik
revizyonu, plan, kanıtlar, ara bulgular, kullanım görünümü ve sonuç. Liste
alanlar ``Annotated`` reducer ile birleşir; paralel ``Send`` sonuçları tek
kanalda benzersiz kimlikle toplanır [LG-WORKFLOWS#C2].

Reducer sözleşmeleri:
- ``merge_messages``: kimlik (role, content, created_at) aynı mesajı düşürür.
- ``merge_by_id``: alan fabrikası; ilk gelen kazanır, aynı kimlik kopyası eklenmez.
- Tekil alanlar (route/plan/outcome/...) LangGraph varsayılanı olan son-yazan-kazanır
  kanallardır; bunlara yalnız tek node yazar.

Serileştirme: state yalnız BusinessModel ve basit tipler taşır; ``serialize_state``
/``deserialize_state`` checkpoint payload'ını üretir ve şema sürümünü denetler.
Büyük kaynak metinleri state'e girmez; ``ArtifactRef`` referansı taşınır
(plan A2: "Büyük kaynak metinlerini ayrı depoda tut; checkpoint içinde referans taşı").
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Callable, TypedDict

from pydantic import TypeAdapter

from ..errors import AgentErrorCode, PortError
from ..models import (
    AgentOutcome,
    ConversationTurn,
    EvidenceItem,
    ExecutionContext,
    ResearchFinding,
    ResearchPlan,
    RouteDecision,
)
from .artifacts import ArtifactRef
from .events import NodeErrorRecord, UsageEvent

__all__ = [
    "STATE_SCHEMA_VERSION",
    "SubtaskInput",
    "AgentState",
    "merge_messages",
    "merge_by_id",
    "merge_evidence",
    "merge_findings",
    "merge_usage_events",
    "merge_error_records",
    "merge_artifact_refs",
    "serialize_state",
    "deserialize_state",
]

#: Checkpoint payload şema sürümü; uyumsuz sürüm anlaşılır hatayla reddedilir (A8 genişletir).
STATE_SCHEMA_VERSION = 1


def merge_messages(left: list[ConversationTurn], right: list[ConversationTurn]) -> list[ConversationTurn]:
    """Konuşma mesajlarını sıra korunarak birleştirir; birebir kopyayı düşürür.

    Kimlik ``(role, content, created_at)`` üçlüsüdür; node'un tekrar yürütülmesi
    aynı mesajı üretirse kanalda tek kopya kalır.
    """
    merged = list(left)
    seen = {(m.role, m.content, m.created_at) for m in merged}
    for message in right:
        key = (message.role, message.content, message.created_at)
        if key not in seen:
            seen.add(key)
            merged.append(message)
    return merged


def merge_by_id(id_field: str) -> Callable[[list[Any], list[Any]], list[Any]]:
    """Verilen kimlik alanına göre birleştiren reducer fabrikası; ilk gelen kazanır."""

    def reducer(left: list[Any], right: list[Any]) -> list[Any]:
        merged = list(left)
        seen = {getattr(item, id_field) for item in merged}
        for item in right:
            key = getattr(item, id_field)
            if key not in seen:
                seen.add(key)
                merged.append(item)
        return merged

    reducer.__name__ = f"merge_by_id({id_field!r})"
    reducer.__qualname__ = reducer.__name__
    return reducer


merge_evidence = merge_by_id("evidence_id")
merge_findings = merge_by_id("finding_id")
merge_usage_events = merge_by_id("event_id")
merge_error_records = merge_by_id("error_id")
merge_artifact_refs = merge_by_id("artifact_id")


class SubtaskInput(TypedDict):
    """``Send`` ile paralel worker'a taşınan girdi; state'in tamamı taşınmaz."""

    sub_question: str
    sub_index: int
    round: int


class AgentState(TypedDict, total=False):
    """Agent çalışmasının ortak state'i; tüm alanlar serileştirilebilir."""

    schema_version: int
    run_id: str

    #: Girdi bağlamı ve bir kez hesaplanmış router kararı (A1 sözleşmesi).
    context: ExecutionContext
    route: RouteDecision | None
    article_revision: int | None

    #: Araştırma planı ve sıradaki ``Send`` yığını (orchestrator yazar, worker okumaz).
    plan: ResearchPlan | None
    pending_subtasks: list[SubtaskInput]
    research_round: int

    #: Koleksiyon kanalları: reducer'lı, paralel yazıma güvenli.
    messages: Annotated[list[ConversationTurn], merge_messages]
    evidence: Annotated[list[EvidenceItem], merge_evidence]
    findings: Annotated[list[ResearchFinding], merge_findings]
    usage_events: Annotated[list[UsageEvent], merge_usage_events]
    errors: Annotated[list[NodeErrorRecord], merge_error_records]
    artifact_refs: Annotated[list[ArtifactRef], merge_artifact_refs]

    #: Terminal sonuç; yalnız finalize/respond yazar.
    outcome: AgentOutcome | None


_MODEL_FIELDS: dict[str, type] = {
    "context": ExecutionContext,
    "route": RouteDecision,
    "plan": ResearchPlan,
    "outcome": AgentOutcome,
}
_LIST_MODEL_FIELDS: dict[str, type] = {
    "messages": ConversationTurn,
    "evidence": EvidenceItem,
    "findings": ResearchFinding,
    "usage_events": UsageEvent,
    "errors": NodeErrorRecord,
    "artifact_refs": ArtifactRef,
}
_SIMPLE_FIELDS = ("run_id", "article_revision", "research_round", "pending_subtasks")


def serialize_state(state: AgentState) -> bytes:
    """State'i JSON checkpoint payload'ına çevirir; model alanları dict'e iner."""
    values: dict[str, Any] = {}
    for field, model_type in _MODEL_FIELDS.items():
        if state.get(field) is not None:
            values[field] = state[field].model_dump(mode="json")
    for field, model_type in _LIST_MODEL_FIELDS.items():
        items = state.get(field) or []
        values[field] = [item.model_dump(mode="json") for item in items]
    for field in _SIMPLE_FIELDS:
        if field in state and state[field] is not None:
            values[field] = state[field]
    payload = {
        "schema_version": state.get("schema_version", STATE_SCHEMA_VERSION),
        "values": values,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def deserialize_state(payload: bytes, *, expected_run_id: str | None = None) -> AgentState:
    """Checkpoint payload'ını state'e geri yükler.

    Raises:
        PortError: ``validation_error`` — payload bozuk, şema sürümü bilinmiyor
            veya başka run'a ait.
    """
    try:
        document = json.loads(payload.decode("utf-8"))
        version = document["schema_version"]
        values: dict[str, Any] = document["values"]
    except (ValueError, UnicodeDecodeError, KeyError, TypeError) as error:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"state checkpoint payload'ı çözümlenemedi: {error}",
            port="deserialize_state",
        ) from error
    if version != STATE_SCHEMA_VERSION:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            f"state şema sürümü uyumsuz: payload={version}, beklenen={STATE_SCHEMA_VERSION}",
            port="deserialize_state",
        )
    if expected_run_id is not None and values.get("run_id") != expected_run_id:
        raise PortError(
            AgentErrorCode.VALIDATION_ERROR,
            "state checkpoint payload'ı istenen run'a ait değil",
            port="deserialize_state",
        )

    state: dict[str, Any] = {"schema_version": version}
    for field, model_type in _MODEL_FIELDS.items():
        if field in values and values[field] is not None:
            state[field] = model_type.model_validate(values[field])
    for field, model_type in _LIST_MODEL_FIELDS.items():
        adapter = TypeAdapter(list[model_type])
        state[field] = adapter.validate_python(values.get(field) or [])
    for field in _SIMPLE_FIELDS:
        if field in values:
            state[field] = values[field]
    return state  # type: ignore[return-value]
