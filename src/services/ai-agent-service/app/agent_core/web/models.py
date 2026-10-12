"""Web araç katmanı iş modelleri (plan A6).

Plan: "Kaynak modeli URL, final URL, başlık, yayıncı, varsa yayın tarihi,
erişim tarihi, içerik hash'i, çıkarma durumu, kaynak türü ve kanıtları
taşısın. Bulunmayan tarihleri uydurma."

``models.sources.SourceReference`` A1'de sabitlenmiş ve bu fazın dosya
sahipliği dışındadır; bu nedenle A6'nın zengin kaydı ``WebSourceRecord`` olarak
burada yaşar ve ``to_source_reference`` ile graf katmanına (A7) daraltılabilir
dönüşüm sunar. ``models.sources.SourceReference`` ve ``EvidenceItem`` DONMUŞ
sözleşmeler olduğu için yalnız tüketilir, değiştirilmez.

``ExtractionStatus``: erişim engeli, CAPTCHA şüphesi ve çıkarılamayan içeriğin
plan gereği raporlanması taşıyıcısıdır — taşıma koşulları istisna değil,
durum alanıyla bildirilir (HTTP düzeyi arızalar PortError olarak yükselir).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, NonNegativeInt

from ..models import BusinessModel, HashHex, UtcDatetime
from ..models.sources import SourceReference

__all__ = [
    "DuplicateKind",
    "EvidenceKind",
    "ExtractionStatus",
    "ExtractedText",
    "FetchedContent",
    "SourceAssessment",
    "SourceEvidence",
    "SourceType",
    "WebSourceRecord",
]


class ExtractionStatus(StrEnum):
    """Çıkarma sonucu; ``ok`` dışındaki değerler raporlanır, uydurulmaz."""

    OK = "ok"
    EMPTY = "empty"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    TOO_LARGE = "too_large"
    DECODE_ERROR = "decode_error"
    BLOCKED = "blocked"
    CAPTCHA_SUSPECTED = "captcha_suspected"
    FAILED = "failed"


class SourceType(StrEnum):
    """Kaynak türü; plan: resmî belge, özgün araştırma ve proje kaynağı önceliklidir."""

    OFFICIAL_DOCS = "official_docs"
    ORIGINAL_RESEARCH = "original_research"
    PROJECT_SOURCE = "project_source"
    ENGINEERING_ARTICLE = "engineering_article"
    NEWS = "news"
    BLOG = "blog"
    FORUM = "forum"
    UNKNOWN = "unknown"


class EvidenceKind(StrEnum):
    """Kanıtın geldiği katman; snippet kanıtı tam sayfa sayılmaz (plan A6)."""

    FULL_PAGE = "full_page"
    SEARCH_SNIPPET = "search_snippet"
    PAGE_METADATA = "page_metadata"


class DuplicateKind(StrEnum):
    """Kopya/aynı kaynak ayrıştırması (plan A6: benzer ve kopya kaynaklar ayrıştırılır)."""

    NONE = "none"
    EXACT = "exact"
    NEAR = "near"


class FetchedContent(BusinessModel):
    """Tek HTTP getiriminin ham sonucu; ``extract_text`` girdisi."""

    requested_url: str = Field(min_length=1, max_length=2048)
    final_url: str = Field(min_length=1, max_length=2048)
    status_code: NonNegativeInt
    content_type: str | None = None
    body: bytes = Field(default=b"", max_length=10_000_000)
    fetched_at: UtcDatetime
    redirect_count: NonNegativeInt = 0


class SourceEvidence(BusinessModel):
    """Kaynağın taşıdığı tek kanıt parçası; A7 kanıt eşlemesinin hammaddesi."""

    kind: EvidenceKind
    excerpt: str = Field(min_length=1, max_length=2000)
    char_start: NonNegativeInt | None = None
    char_end: NonNegativeInt | None = None
    collected_at: UtcDatetime


class ExtractedText(BusinessModel):
    """``extract_text`` aracının çıktısı: temizlenmiş metin ve sayfa metadata'sı.

    ``published_at`` yalnız sayfada güvenilir bir tarih varsa doludur; bulunmayan
    tarih ``None`` kalır, uydurulmaz (plan A6).
    """

    url: str = Field(min_length=1, max_length=2048)
    final_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    publisher: str | None = Field(default=None, max_length=256)
    published_at: UtcDatetime | None = None
    accessed_at: UtcDatetime
    content_type: str | None = None
    extraction_status: ExtractionStatus
    text: str = Field(default="", max_length=500_000)
    content_hash: HashHex


class WebSourceRecord(BusinessModel):
    """Plan A6 kaynak modeli: URL, final URL, başlık, yayıncı, varsa yayın
    tarihi, erişim tarihi, içerik hash'i, çıkarma durumu, kaynak türü ve kanıtlar.

    ``content_hash`` normalize edilmiş çıkarılmış metnin SHA-256 özetidir; kopya
    tespiti ve A7 kanıt bağlamının kararlı temelidir.
    """

    url: str = Field(min_length=1, max_length=2048)
    final_url: str = Field(min_length=1, max_length=2048)
    title: str | None = Field(default=None, max_length=512)
    publisher: str | None = Field(default=None, max_length=256)
    published_at: UtcDatetime | None = None
    accessed_at: UtcDatetime
    content_hash: HashHex
    extraction_status: ExtractionStatus
    source_type: SourceType | None = None  # assess_source doldurur
    text: str = Field(default="", max_length=500_000)
    content_type: str | None = None
    full_page_read: bool = True  # False: yalnız arama snippet'i var
    evidences: list[SourceEvidence] = Field(default_factory=list)

    def to_source_reference(self, *, now: datetime | None = None) -> SourceReference:
        """DONMUŞ A1 sözleşmesine daraltır; A7 kanıt eşlemesi bunu kullanır."""
        accessed = self.accessed_at if now is None else now
        return SourceReference(
            kind="web",
            url=self.final_url,
            accessed_at=accessed,
            title=self.title,
        )


class SourceAssessment(BusinessModel):
    """``assess_source`` aracının çıktısı: tür, öncelik, kopya ve bağımsızlık analizi.

    ``priority_rank`` 0 en önceliklidir (resmî belge / özgün araştırma / proje
    kaynağı — plan A6). ``duplicate_of`` karşı kaynağın kaynak kimliğidir.
    """

    url: str = Field(min_length=1, max_length=2048)
    source_id: str = Field(min_length=1, max_length=512)
    source_type: SourceType
    priority_rank: NonNegativeInt
    preferred: bool
    publisher_group: str = Field(min_length=1, max_length=256)
    duplicate_of: str | None = Field(default=None, max_length=512)
    duplicate_kind: DuplicateKind = DuplicateKind.NONE
    duplicate_similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    full_page_read: bool
    distinct_publisher_groups: NonNegativeInt = 1
    notes: list[str] = Field(default_factory=list)
