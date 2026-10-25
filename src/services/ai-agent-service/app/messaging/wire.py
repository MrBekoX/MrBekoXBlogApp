"""Run wire sürümü (karar kaydı K4): run mesajlarını run'ın sürümüyle kurma kuralları.

Bir run'ın wire sürümü kabul anında execute zarfının ``schema_version``'ından
belirlenir, ``agent.jobs.wire_version`` kolonunda (migration 0005) saklanır ve
run boyunca DEĞİŞMEZ. Bu modül tüm run mesajı üreticilerinin (job_store kabul +
deneme tükenmesi, control_store iptal/deadline, reaper, events yayıncısı, worker
terminal/ara olayları, wire_drain) ortak kurma yoludur:

- ``compose_run_envelope``: (sürüm, tür) kaydından payload DTO'sunu seçer, payload'ı
  doğrular ve zarfı o sürümle kurar; ardından TÜKETİCİ ile aynı doğrulayıcıdan
  (``parse_envelope``) geçirir — çapraz kurallar (profile kaynak biçimi, pinlenmiş
  snapshot bağı) üretici tarafında da uygulanır. İhlal ``AgentContractError``.
- ``outbox_route``: outbox satırının exchange/routing key'i zarfın kendi
  sürümünden gelir (``.v1``/``.v2``); tek global sürüm sabiti kullanılmaz.
- ``versioned_payload``: v2'ye özgü alanlar yalnız v2 run'ında taşınır; v1 run'ı
  donmuş v1 şekliyle kalır (v1 consumer'ları için kırıcı alan eklenmez).
- ``to_transport_citation``/``to_transport_profile_snapshot``: domain → transport
  dönüşümü sürüme göre (v1: article|web; v2: article|web|profile). v1 run'ı profile
  kaynağı TAŞIYAMAZ (provenance article/web'e daraltılmaz) — ``WireVersionMismatch``.

DB tarafındaki karşılık: ``outbox_events`` BEFORE INSERT tetikleyicisi zarf
``schema_version`` ≠ ``jobs.wire_version`` ise kaydı reddeder (sürüm karışması
DB düzeyinde de engellenir).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from agent_core.telemetry import current_traceparent

from .contracts import (
    SUPPORTED_SCHEMA_VERSIONS,
    WIRE_VERSION_V1,
    WIRE_VERSION_V2,
    AgentEnvelope,
    AgentProfileSnapshotRef,
    AgentSourceReferenceV2,
    Producer,
    parse_envelope,
    spec_for,
)
from .contracts.payloads import AgentSourceReference

__all__ = [
    "WORKER_WIRE_MAX",
    "WORKER_WIRE_MAX_SETTING",
    "WireVersionMismatch",
    "assert_contract",
    "compose_run_envelope",
    "normalize_wire_version",
    "outbox_route",
    "to_transport_citation",
    "to_transport_profile_snapshot",
    "utc_iso",
    "versioned_payload",
]

#: Bu kod tabanının yürütebildiği en yüksek run wire sürümü.
WORKER_WIRE_MAX = max(SUPPORTED_SCHEMA_VERSIONS)

#: Worker DB oturumunun bildirdiği GUC (migration 0005 claim izolasyon tetikleyicisi
#: okur). Ayar yoksa tetikleyici 1 varsayar: eski worker v2 satırını claim/kapatamaz.
WORKER_WIRE_MAX_SETTING = "agent.worker_wire_max"


class WireVersionMismatch(ValueError):
    """Run'ın wire sürümü ile taşınmak istenen içerik uyuşmuyor (ör. v1 run'ında profile kaynağı)."""


def normalize_wire_version(value: Any) -> int:
    """DB/kayıt değerini desteklenen sürüme çevirir; eksik değer v1'dir (eski kayıtlar)."""

    if value is None:
        return WIRE_VERSION_V1
    version = int(value)
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise WireVersionMismatch(f"desteklenmeyen run wire sürümü: {version}")
    return version


def utc_iso(value: datetime | None = None) -> str:
    """Sözleşme ``UtcIsoString`` biçimi ('Z' sonekli, saniye hassasiyeti)."""

    moment = value or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def versioned_payload(
    schema_version: int,
    fields: Mapping[str, Any],
    v2_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sürüm şekline göre payload alanları: None atılır, v2 alanları yalnız v2'de eklenir."""

    payload = {key: value for key, value in fields.items() if value is not None}
    if schema_version >= WIRE_VERSION_V2 and v2_fields:
        payload.update({key: value for key, value in v2_fields.items() if value is not None})
    return payload


def compose_run_envelope(
    *,
    schema_version: int,
    message_type: str,
    run_id: str,
    conversation_id: str,
    correlation_id: str,
    payload: Mapping[str, Any],
    causation_id: str | None = None,
    occurred_at: datetime | str | None = None,
    message_id: str | None = None,
    new_message_id: Callable[[], uuid.UUID] | None = None,
    producer: Producer = Producer.AGENT_PY,
) -> AgentEnvelope:
    """Run mesajını run'ın sürümüyle kurar ve tüketici doğrulayıcısından geçirir.

    Raises:
        UnknownMessageSpec: (sürüm, tür) sözleşmede yok (sözleşme dışı mesaj üretilmez).
        pydantic.ValidationError: payload sürüm DTO'suna aykırı.
        AgentContractError: tüketici doğrulayıcısının çapraz kuralı ihlal edildi.
    """

    spec = spec_for(schema_version, message_type)
    validated = spec.payload_model.model_validate(dict(payload))
    if isinstance(occurred_at, datetime):
        occurred = utc_iso(occurred_at)
    else:
        occurred = occurred_at or utc_iso()
    if message_id is None:
        message_id = str((new_message_id or uuid.uuid4)())
    fields: dict[str, Any] = dict(
        message_id=message_id,
        message_type=message_type,
        schema_version=schema_version,
        run_id=run_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        occurred_at=occurred,
        producer=producer,
        trace_context=current_traceparent(),
        payload=validated.model_dump(exclude_none=True),
    )
    envelope = AgentEnvelope(**{key: value for key, value in fields.items() if value is not None})
    # Tüketiciyle AYNI doğrulayıcı: çapraz kurallar üretici tarafında da geçerli.
    parse_envelope(envelope.model_dump_json(exclude_none=True))
    return envelope


def outbox_route(envelope: AgentEnvelope) -> tuple[str, str]:
    """Zarfın kendi sürümünün kaydından (exchange, routing_key)."""

    spec = spec_for(envelope.schema_version, envelope.message_type)
    return spec.exchange, spec.routing_key


def to_transport_profile_snapshot(snapshot: Any) -> AgentProfileSnapshotRef | None:
    """Domain ``ProfileSnapshotRef`` (veya eşdeğer eşleme) → transport referansı."""

    if snapshot is None:
        return None
    if isinstance(snapshot, AgentProfileSnapshotRef):
        return snapshot
    if isinstance(snapshot, Mapping):
        return AgentProfileSnapshotRef.model_validate(dict(snapshot))
    return AgentProfileSnapshotRef(
        profile_id=str(snapshot.profile_id),
        revision=int(snapshot.revision),
        content_hash=str(snapshot.content_hash),
    )


_CITATION_FIELDS = (
    "kind",
    "source_id",
    "title",
    "article_id",
    "article_revision",
    "chunk_index",
    "url",
    "accessed_at",
    "profile_id",
    "profile_revision",
    "profile_content_hash",
    "section_id",
)


def to_transport_citation(citation: Any, schema_version: int) -> AgentSourceReference | AgentSourceReferenceV2:
    """Domain/transport kaynak referansı → sürümün transport modeli.

    ``source_id`` her iki sürümde de taşınır (v1 şeması izin verir; önceki
    dönüşüm onu düşürüyordu). ``TransportModel`` açık null reddeder; None alanlar
    kurucuya hiç geçilmez. v1 run'ında profile kaynağı ``WireVersionMismatch``.
    """

    if isinstance(citation, (AgentSourceReference, AgentSourceReferenceV2)):
        raw = citation.model_dump(exclude_none=True)
    elif isinstance(citation, Mapping):
        raw = {key: value for key, value in citation.items() if value is not None}
    else:
        raw = {
            name: getattr(citation, name, None)
            for name in _CITATION_FIELDS
            if getattr(citation, name, None) is not None
        }
    accessed = raw.get("accessed_at")
    if isinstance(accessed, datetime):
        raw["accessed_at"] = utc_iso(accessed)
    if schema_version >= WIRE_VERSION_V2:
        return AgentSourceReferenceV2(**raw)
    if raw.get("kind") == "profile":
        raise WireVersionMismatch(
            "v1 run'ı profile kaynağı taşıyamaz; profil provenance'ı article/web'e daraltılmaz"
        )
    profile_keys = [key for key in ("profile_id", "profile_revision", "profile_content_hash", "section_id") if key in raw]
    if profile_keys:
        raise WireVersionMismatch(f"v1 kaynak referansı profil alanı taşıyamaz: {', '.join(profile_keys)}")
    return AgentSourceReference(**raw)


def assert_contract(envelope: AgentEnvelope) -> None:
    """Hazır zarfı tüketici doğrulayıcısından geçirir (``AgentContractError``)."""

    parse_envelope(envelope.model_dump_json(exclude_none=True))

