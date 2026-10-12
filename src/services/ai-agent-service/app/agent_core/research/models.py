"""Derin araştırma akışının yerel iş modelleri (plan A7).

Plan A7: "EvidenceItem; claim_id, source_id, destekleyen metin aralığı,
source_revision veya content_hash, destek türü ve kısa gerekçe içersin."
``EvidenceItem``/``SourceReference`` A1'de sabitlenmiş DONMUŞ sözleşmelerdir
ve bu fazın dosya sahipliği dışındadır; A6 ``WebSourceRecord`` + ``record_to_
evidence`` daraltma deseni burada da izlenir: zengin kayıt yerel
``ClaimEvidenceRecord`` olarak yaşar ve ``to_evidence_item`` ile DONMUŞ
``EvidenceItem``'a daraltılır.

TASARIM NOTU (plan A7): "Anlamsal destek değerlendirmesinin hatasız doğruluk
garantisi vermediğini tasarımda belirt; desteklenmeyen iddiayı çıkar veya
belirsizleştir." ``support`` alanı sezgisel sınıflamanın sonucudur ve
hatasız doğruluk garantisi TAŞIMAZ; ``UNCLEAR`` kanıt bulgulara bağlanmaz,
belirsizlik bölümüne düşer [AC-SELF-RAG#C2].
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, TypedDict

from pydantic import Field, NonNegativeInt, PositiveInt

from ..models import (
    BusinessModel,
    HashHex,
    Identifier,
    NonEmptyText,
    ResearchFinding,
    SourceReference,
    UtcDatetime,
)

if TYPE_CHECKING:
    from ..models import EvidenceItem  # noqa: F401 - dönüş tipi ipucu

__all__ = [
    "ClaimEvidenceRecord",
    "ClaimRecord",
    "ComparisonNote",
    "CoverageAssessment",
    "GatherTask",
    "ResearchFlowConfig",
    "ResearchReport",
    "SourceLedgerEntry",
    "SupportKind",
]


class SupportKind(StrEnum):
    """Kanıtın iddiaya desteği; sezgisel sınıflama sonucudur, kesinlik iddiası değildir."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    UNCLEAR = "unclear"


class ClaimRecord(BusinessModel):
    """Makaleden çıkarılan tek iddia; metin aralığı makale içindedir."""

    claim_id: Identifier
    article_id: Identifier
    article_revision: NonNegativeInt
    text: str = Field(min_length=1, max_length=2000)
    char_start: NonNegativeInt
    char_end: NonNegativeInt


class SourceLedgerEntry(BusinessModel):
    """Okunan web kaynağının kayıt defteri girişi (A6 ``WebSourceRecord`` daralması).

    Büyük metin state'e girmez: sayfa metni ``ArtifactStore``'da tutulur,
    giriş yalnız ``artifact_id`` referansı taşır (plan A2). ``source_id``
    A1 kanonik web kimliğidir (url+erişim damgası).
    """

    source_id: Identifier
    url: str = Field(min_length=1, max_length=2048)
    final_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    publisher: str | None = Field(default=None, max_length=256)
    published_at: UtcDatetime | None = None
    accessed_at: UtcDatetime
    content_hash: HashHex
    extraction_status: str = Field(default="ok", max_length=64)
    source_type: str | None = Field(default=None, max_length=64)
    priority_rank: NonNegativeInt = 2
    full_page_read: bool = True
    artifact_id: Identifier
    duplicate_of: str | None = Field(default=None, max_length=512)

    def to_source_reference(self) -> SourceReference:
        """DONMUŞ A1 sözleşmesine daraltır; ``source_id`` kanonik türetmeyle aynıdır."""
        return SourceReference(
            kind="web",
            url=self.final_url,
            accessed_at=self.accessed_at,
            title=self.title,
        )


class ClaimEvidenceRecord(BusinessModel):
    """İddia başına kanıt kaydı (plan A7 alan kümesi).

    ``evidence_id`` içerik adreslidir (claim|source|aralık|destek özeti);
    tekrar değerlendirme aynı kimliği üretir ve reducer kopyayı düşürür.
    Programatik doğrulama: ``evaluation.verify_claim_evidence`` kaynak ID
    varlığını, URL eşleşmesini ve metin aralığını denetler; geçersiz kayıt
    kanıt havuzuna girmez.
    """

    evidence_id: Identifier
    claim_id: Identifier
    source_id: Identifier
    url: str = Field(min_length=1, max_length=2048)
    excerpt: str = Field(min_length=1, max_length=2000)
    char_start: NonNegativeInt
    char_end: NonNegativeInt
    source_content_hash: HashHex
    support: SupportKind
    rationale: str = Field(min_length=1, max_length=500)

    def to_evidence_item(self, *, collected_at: datetime) -> "EvidenceItem":
        """DONMUŞ A1 ``EvidenceItem`` sözleşmesine daraltır (A6 köprü deseni).

        ``collected_at`` kanıtın toplandığı andır; DONMUŞ ``SourceReference``
        web sözleşmesi erişim zamanı istediğinden aynı damga kaynağa da yazılır.
        """
        from ..models import EvidenceItem  # yerel import: döngüsel risk yok, gecikmeli

        return EvidenceItem(
            evidence_id=self.evidence_id,
            source=SourceReference(kind="web", url=self.url, accessed_at=collected_at),
            excerpt=self.excerpt,
            collected_at=collected_at,
        )


class CoverageAssessment(BusinessModel):
    """Kapsam ve çelişki değerlendirmesi (plan A7 adım 6-7).

    ``uncovered_claim_ids``: hiç ``supports`` kanıtı taşımayan iddialar —
    rapor bulgusuna bağlanmaz, belirsizlik olarak bildirilir.
    """

    round: PositiveInt
    uncovered_claim_ids: list[str] = []
    contradicted_claim_ids: list[str] = []
    unresolved_sub_questions: list[str] = []
    next_round_scheduled: bool = False
    budget_note: str | None = Field(default=None, max_length=500)


class ComparisonNote(BusinessModel):
    """Bulgunun makaleyle ve alternatiflerle karşılaştırma sonucu (plan A7 adım 8)."""

    claim_id: Identifier
    relation: Literal["agrees", "contradicts", "unclear"]
    detail: str = Field(min_length=1, max_length=1000)


class ResearchReport(BusinessModel):
    """Yapılandırılmış araştırma raporu (plan A7 bölüm kümesi).

    ``text`` dışarıya giden bütün rapor metnidir; ``summary`` model üretimi
    kısa sonuçtur ve kontrol düğümünde uydurma kaynak kimliği ayıklanmıştır.
    ``sources`` yalnız kayıt defterindeki doğrulanmış kaynakları taşır.
    """

    report_id: Identifier
    run_id: Identifier
    question: NonEmptyText
    summary: NonEmptyText
    scope: NonEmptyText
    article_relation: NonEmptyText
    generated_at: UtcDatetime
    comparison: list[ComparisonNote] = []
    findings: list[ResearchFinding] = []
    uncertainties: list[str] = []
    sources: list[SourceReference] = []
    completeness: Literal["complete", "partial"]
    completeness_note: NonEmptyText
    text: str = Field(min_length=1, max_length=200000)


class ResearchFlowConfig(BusinessModel):
    """Araştırma akışının davranış sınırları; hepsi sınırlı ve denetlenebilirdir."""

    #: Çıkarılacak en fazla makale iddiası.
    max_claims: PositiveInt = 6
    #: Tek arama sorgusundan okunacak en fazla kaynak adayı.
    max_candidates_per_query: PositiveInt = 3
    #: İddia-soru ilgisi ve destek sınıflaması için en az ortak anlamlı terim.
    min_claim_overlap: int = Field(default=2, ge=1)
    #: Bulgu başına rapora taşınacak en fazla kanıt kimliği.
    max_evidence_per_finding: PositiveInt = 6


class GatherTask(TypedDict):
    """``Send`` ile paralel worker'a taşınan toplama görevi (state'in tamamı taşınmaz).

    ``purpose``: ``sub_question`` — alt soru sorgusu; ``claim_check`` —
    karşılanmayan iddianın düzeltilmiş sorgusu (ikinci tur).
    """

    query: str
    round: int
    purpose: str
    ref_id: str
    sub_question: str
