"""Kategorize sözleşme doğrulayıcı: parse_envelope.

Adım sırası .NET ``AgentContractValidator`` ile birebir aynıdır:
boyut → JSON çözümü → zarf kuralları → sürüm → tür kaydı → run kimliği/deadline/
üretici yönü → payload kuralları → zarf bağlantısı ve eksik-alan çapraz kuralları.
Ortak fixture seti iki tarafın aynı girdi için aynı kategoriyi üretmesini sabitler.

Gövde yalnız JSON olarak çözümlenir; pickle veya keyfi nesne deserialization
kullanılmaz (plan satır 239).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .envelope import AgentEnvelope
from .errors import AgentContractError, ContractErrorCategory
from .payloads import (
    AgentActionProposedV1,
    AgentActionResultV1,
    AgentRunCancelledV1,
    AgentRunCompletedV1,
    AgentRunFailedV1,
    AgentRunNeedsInputV1,
    AgentRunPartiallyCompletedV1,
    ArticleContentChangedV1,
)
from .registry import MAX_PAYLOAD_BYTES, SCHEMA_VERSION, MESSAGE_TYPE_REGISTRY, MessageTypeSpec

__all__ = ["ParsedEnvelope", "parse_envelope"]

_USAGE_CARRIERS = (
    AgentRunCompletedV1,
    AgentRunPartiallyCompletedV1,
    AgentRunNeedsInputV1,
    AgentRunFailedV1,
    AgentRunCancelledV1,
)


@dataclass(frozen=True)
class ParsedEnvelope:
    """Doğrulanmış zarf, tür bazlı payload modeli ve kaydı."""

    envelope: AgentEnvelope
    payload: Any
    spec: MessageTypeSpec


def parse_envelope(raw: bytes | str, *, max_payload_bytes: int = MAX_PAYLOAD_BYTES) -> ParsedEnvelope:
    """Ham gövdeyi doğrular; ihlalde ``AgentContractError`` fırlatır.

    raw yalnız JSON metni veya UTF-8 baytları olabilir; nesne kabul edilmez —
    sözleşme sınırını yalnız serileştirilmiş veri geçebilir.
    """

    if isinstance(raw, (bytes, bytearray)):
        encoded = bytes(raw)
    elif isinstance(raw, str):
        encoded = raw.encode("utf-8")
    else:
        raise TypeError("parse_envelope yalnız JSON metni (str) veya UTF-8 baytı (bytes) kabul eder")

    if len(encoded) > max_payload_bytes:
        raise AgentContractError(
            ContractErrorCategory.OVERSIZED,
            "payload",
            f"gövde {max_payload_bytes} bayt üst sınırını aşıyor: {len(encoded)} bayt",
        )

    try:
        document = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise AgentContractError(ContractErrorCategory.BAD_FORMAT, "body", f"gövde geçerli JSON değil: {exc.msg}") from exc

    if not isinstance(document, dict):
        raise AgentContractError(ContractErrorCategory.WRONG_TYPE, "body", "zarf bir JSON nesnesi olmalıdır")

    try:
        envelope = AgentEnvelope.model_validate(document)
    except ValidationError as exc:
        raise _to_contract_error(exc) from exc

    if envelope.schema_version != SCHEMA_VERSION:
        raise AgentContractError(
            ContractErrorCategory.UNKNOWN_VERSION,
            "schema_version",
            f"bilinmeyen sözleşme sürümü: {envelope.schema_version}",
        )

    spec = MESSAGE_TYPE_REGISTRY.get(envelope.message_type)
    if spec is None:
        raise AgentContractError(
            ContractErrorCategory.UNKNOWN_TYPE,
            "message_type",
            f"bilinmeyen mesaj türü: {envelope.message_type}",
        )

    if spec.requires_run_identity and (envelope.run_id is None or envelope.conversation_id is None):
        raise AgentContractError(
            ContractErrorCategory.MISSING_FIELD,
            "run_id",
            f"{envelope.message_type} için run_id ve conversation_id zorunludur",
        )
    if not spec.requires_run_identity and (envelope.run_id is not None or envelope.conversation_id is not None):
        raise AgentContractError(
            ContractErrorCategory.WRONG_TYPE,
            "run_id",
            f"{envelope.message_type} run kimliği taşımaz",
        )

    if spec.requires_deadline and envelope.deadline_at is None:
        raise AgentContractError(
            ContractErrorCategory.MISSING_FIELD,
            "deadline_at",
            f"{envelope.message_type} için deadline_at zorunludur",
        )

    if envelope.producer not in spec.allowed_producers:
        raise AgentContractError(
            ContractErrorCategory.PRODUCER_MISMATCH,
            "producer",
            f"{envelope.message_type} yönü için üretici izinli değil: {envelope.producer.value}",
        )

    try:
        payload = spec.payload_model.model_validate(envelope.payload)
    except ValidationError as exc:
        raise _to_contract_error(exc, prefix="payload.") from exc

    _check_envelope_binding(envelope, payload)
    _check_missing_rules(payload)
    return ParsedEnvelope(envelope=envelope, payload=payload, spec=spec)


def _to_contract_error(exc: ValidationError, *, prefix: str = "") -> AgentContractError:
    """İlk Pydantic hatasını kategorize eder; kategori eşlemesi .NET doğrulayıcıyla aynıdır."""

    error = exc.errors()[0]
    error_type = error["type"]
    field = prefix + ".".join(str(part) for part in error["loc"])
    if error_type == "missing":
        category = ContractErrorCategory.MISSING_FIELD
    elif error_type == "extra_forbidden":
        category = ContractErrorCategory.EXTRA_FIELD
    elif error_type in ("string_pattern_mismatch", "utc_format"):
        category = ContractErrorCategory.BAD_FORMAT
    else:
        category = ContractErrorCategory.WRONG_TYPE
    return AgentContractError(category, field, error["msg"])


def _check_envelope_binding(envelope: AgentEnvelope, payload: Any) -> None:
    """Zarf bağlantısı: usage.run_id ve proposal run_id zarf run_id ile uyuşmalıdır."""

    if isinstance(payload, _USAGE_CARRIERS) and payload.usage is not None:
        if payload.usage.run_id != envelope.run_id:
            raise AgentContractError(
                ContractErrorCategory.WRONG_TYPE,
                "payload.usage.run_id",
                "usage.run_id zarf run_id ile uyuşmuyor",
            )

    if isinstance(payload, AgentRunCompletedV1) and payload.action_proposal is not None:
        if payload.action_proposal.run_id != envelope.run_id:
            raise AgentContractError(
                ContractErrorCategory.WRONG_TYPE,
                "payload.action_proposal.run_id",
                "action_proposal.run_id zarf run_id ile uyuşmuyor",
            )

    if isinstance(payload, AgentActionProposedV1) and payload.run_id != envelope.run_id:
        raise AgentContractError(
            ContractErrorCategory.WRONG_TYPE,
            "payload.run_id",
            "payload.run_id zarf run_id ile uyuşmuyor",
        )


def _check_missing_rules(payload: Any) -> None:
    """Kategori 'eksik alan' olan çapraz kurallar (.NET tarafıyla aynı sınıflandırma)."""

    if isinstance(payload, AgentActionResultV1):
        if payload.outcome == "accepted" and payload.applied_article_revision is None:
            raise AgentContractError(
                ContractErrorCategory.MISSING_FIELD,
                "payload.applied_article_revision",
                "kabul edilen eylem için applied_article_revision zorunludur",
            )

    if isinstance(payload, ArticleContentChangedV1):
        if payload.action == "updated" and payload.content_hash is None:
            raise AgentContractError(
                ContractErrorCategory.MISSING_FIELD,
                "payload.content_hash",
                "updated eylemi için content_hash zorunludur",
            )
        if payload.action == "unpublished" and payload.content_hash is not None:
            raise AgentContractError(
                ContractErrorCategory.WRONG_TYPE,
                "payload.content_hash",
                "unpublished eylemi content_hash taşımaz",
            )

    if isinstance(payload, (AgentRunCompletedV1, AgentRunPartiallyCompletedV1)):
        if payload.answer is None and payload.report is None:
            raise AgentContractError(
                ContractErrorCategory.MISSING_FIELD,
                "payload.answer",
                "answer veya report zorunludur",
            )
