"""İş birliği hazırlığı yerel iş modelleri (plan A9).

Durum makinesi:

- ``DETAILS_NEEDED``: zorunlu alanların bir kısmı eksik; KISA sorular sorulur,
  çalışma ``needs_input`` ile DURUR ve checkpoint'e saklanır (A8 zarfıyla).
- ``PROPOSAL_REVIEW``: ``ActionProposal`` üretildi; düzenlenebilir özet +
  içerik hash'i kullanıcı onayına sunulur — gönderim yalnız açık onay ve
  backend doğrulamasıyla olur (B9); agent bu fazda KAYIT ATMaz.
- ``RESOLVED``: doğrulanmış ``ValidatedActionResult`` alındı; başarı yalnız
  ``accepted`` sonucundan SONRA bildirilir.

``CollaborationState`` çekirdek içi iş state'idir; ``PreparedRun.collab_state``
additive alanıyla A8 checkpoint zincirinde taşınır.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ..models import ActionProposal, BusinessModel, HashHex, Identifier, NonEmptyText, ValidatedActionResult

__all__ = [
    "COLLAB_STATE_SCHEMA_VERSION",
    "CollabField",
    "CollabResumeInput",
    "CollabResolution",
    "CollabStage",
    "CollaborationDetails",
    "CollaborationState",
    "PurposeKind",
    "REQUIRED_COLLAB_FIELDS",
]

#: ``CollaborationState`` payload şema sürümü; uyumsuz state anlaşılır reddedilir.
COLLAB_STATE_SCHEMA_VERSION = 1


class CollabField(StrEnum):
    """İş birliği detay alanları; ``budget`` isteğe bağlıdır (plan A9)."""

    PURPOSE = "purpose"
    SCOPE = "scope"
    TIMELINE = "timeline"
    BUDGET = "budget"
    CONTACT = "contact"


#: Zorunlu alanlar: amaç, kapsam, takvim, iletişim. Bütçe "isteğe bağlı"dir —
#: yokluğu sorulmaz (plan A9: "Amaç, kapsam, takvim, isteğe bağlı bütçe").
REQUIRED_COLLAB_FIELDS: tuple[CollabField, ...] = (
    CollabField.PURPOSE,
    CollabField.SCOPE,
    CollabField.TIMELINE,
    CollabField.CONTACT,
)


class PurposeKind(StrEnum):
    """Çıkarılan amaç kategorisi; kapalı küme — serbest metin uydurulmaz."""

    GUEST_POST = "guest_post"
    TRANSLATION = "translation"
    OPEN_SOURCE = "open_source"
    COLLABORATION = "collaboration"
    OTHER = "other"

    def label(self, language: str) -> str:
        if language.casefold().startswith("tr"):
            return _PURPOSE_LABELS_TR[self]
        return _PURPOSE_LABELS_EN[self]


_PURPOSE_LABELS_TR: dict[PurposeKind, str] = {
    PurposeKind.GUEST_POST: "konuk yazı",
    PurposeKind.TRANSLATION: "çeviri",
    PurposeKind.OPEN_SOURCE: "açık kaynak katkısı",
    PurposeKind.COLLABORATION: "proje iş birliği",
    PurposeKind.OTHER: "diğer",
}

_PURPOSE_LABELS_EN: dict[PurposeKind, str] = {
    PurposeKind.GUEST_POST: "guest post",
    PurposeKind.TRANSLATION: "translation",
    PurposeKind.OPEN_SOURCE: "open-source contribution",
    PurposeKind.COLLABORATION: "project collaboration",
    PurposeKind.OTHER: "other",
}


class CollaborationDetails(BusinessModel):
    """Soru metninden çıkarılan (veya resume girdisiyle tamamlanan) detaylar.

    ``budget`` isteğe bağlıdır; yalnız soruda gerçekten geçiyorsa dolar —
    çıkarılamayan zorunlu alan ``None`` kalır ve soru sorulur, TAHMİN EDİLMEZ.
    """

    purpose: PurposeKind | None = None
    #: Kullanıcının kendi cümlesiyle verdiği amaç (resume cevabı; OTHER için zoruncu değil).
    purpose_note: str | None = Field(default=None, max_length=2000)
    scope: str | None = Field(default=None, max_length=2000)
    timeline: str | None = Field(default=None, max_length=500)
    budget: str | None = Field(default=None, max_length=500)
    contact: str | None = Field(default=None, max_length=2000)

    def missing_required(self) -> list[CollabField]:
        """Dolu olmayan zorunlu alanlar; tanım sırasıyla döner."""
        values = {
            CollabField.PURPOSE: self.purpose is not None,
            CollabField.SCOPE: bool((self.scope or "").strip()),
            CollabField.TIMELINE: bool((self.timeline or "").strip()),
            CollabField.CONTACT: bool((self.contact or "").strip()),
        }
        return [f for f in REQUIRED_COLLAB_FIELDS if not values[f]]


class CollabStage(StrEnum):
    """İş birliği hazırlığının aşaması (bkz. modül docstring'i)."""

    DETAILS_NEEDED = "details_needed"
    PROPOSAL_REVIEW = "proposal_review"
    RESOLVED = "resolved"


class CollabResolution(BusinessModel):
    """Previously validated backend result retained for terminal recovery.

    This is trusted application state, not a cryptographic backend attestation.
    The hash binds recovery to the proposal summary already reviewed by the
    backend; it follows the existing B9 summary-hash contract.
    """

    result: ValidatedActionResult
    proposal_content_hash: HashHex


class CollaborationState(BusinessModel):
    """Checkpoint'te taşınan iş birliği hazırlık state'i.

    ``proposal_content_hash`` onaylanan öneri SÜRÜMÜNÜ sabitler: onay girdisi
    farklı bir sürüme işaret ederse anlaşılır ``validation_error`` ile reddedilir
    (plan A9/B9: "İş birliği kaydı ... belirli proposal sürümüne bağlıdır").
    Hash B9 TEK TANIMdadır (W6 F5): düzenlenebilir özet metninin UTF-8
    SHA-256 özeti — backend ``AgentCollaborationContentHash.Compute(summary)``
    ile aynı değer; öneri kimliği/sürümü değiştiğinde yenilenir.
    """

    schema_version: int = COLLAB_STATE_SCHEMA_VERSION
    stage: CollabStage
    details: CollaborationDetails = Field(default_factory=CollaborationDetails)
    missing_fields: list[str] = []
    questions: list[NonEmptyText] = []
    proposal: ActionProposal | None = None
    proposal_content_hash: HashHex | None = None
    #: Optional for legacy checkpoints; an absent receipt never implies success.
    resolution: CollabResolution | None = None

    @field_validator("schema_version")
    @classmethod
    def _supported_version(cls, value: int) -> int:
        if value != COLLAB_STATE_SCHEMA_VERSION:
            raise ValueError(
                f"collab state şema sürümü desteklenmiyor: {value}, "
                f"desteklenen={COLLAB_STATE_SCHEMA_VERSION}"
            )
        return value


class CollabResumeInput(BusinessModel):
    """Resume girdisi: soru cevapları, düzenleme veya doğrulanmış onay (plan A9).

    Tek çağrıda en fazla BİR işlem yapılabilir: cevaplar + (opsiyonel) düzenleme
    birleşebilir, ancak onay tek başına gelir. Alan anahtarları ``CollabField``
    değerleridir; bilinmeyen alan ``validation_error`` ile reddedilir.
    """

    #: Eksik alan cevapları: alan adı → kullanıcının verdiği değer.
    answers: dict[str, NonEmptyText] = {}
    #: Düzenlenmiş öneri metinleri; mevcut proposal'ın yerine geçer (yeni sürüm).
    edited_summary: str | None = Field(default=None, max_length=8000)
    edited_proposed_content: str | None = Field(default=None, max_length=20000)
    #: Doğrulanmış onay: hangi proposal, hangi içerik sürümü.
    approved_proposal_id: Identifier | None = None
    approved_content_hash: HashHex | None = None

    @model_validator(mode="after")
    def _approval_is_standalone(self) -> "CollabResumeInput":
        if self.approved_proposal_id is not None and (
            self.edited_summary is not None or self.edited_proposed_content is not None
        ):
            raise ValueError(
                "onay girdisi düzenlemeyle birleştirilemez; önce düzenleyin, sonra onaylayın"
            )
        return self
