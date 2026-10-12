"""Site rehberliği yerel iş modelleri (plan A9).

Plan A9 profil/proje davranışının ara değerleri: onaylı makale kataloğu
girdisi (``ArticleCatalogEntry``), uydurulması yasak eksik bilgi alanları
(``MissingInfoField``) ve terminal sonucu sarmalayan ``GuidanceRunResult``.
Tümü ``agent_core`` iş katmanında yaşar; ``src/contracts`` sözleşmelerine
dokunmaz (D015 ayrımıyla aynı gerekçe).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import Field, model_validator

from ..models import AgentOutcome, BusinessModel, Identifier, NonEmptyText

__all__ = [
    "ArticleCatalogEntry",
    "ArticleSuggestion",
    "GuidanceRunResult",
    "MissingInfoField",
]


class ArticleCatalogEntry(BusinessModel):
    """Öneri motorunun girdisi olan onaylı makale kaydı.

    Yalnız çağıranın verdiği doğrulanmış kayıtlarla çalışır: ``url`` zorunludur
    (plan A9: "kısa uygunluk gerekçesi ve kaynak bağlantısı ver"); kataloğu
    bağlı olmayan çalışmada öneri üretilmez, uydurulmaz.
    """

    article_id: Identifier
    title: NonEmptyText = Field(max_length=512)
    url: str = Field(min_length=9, max_length=2048)
    topics: list[str] = []
    summary: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _url_scheme(self) -> "ArticleCatalogEntry":
        if not self.url.lower().startswith(("http://", "https://")):
            raise ValueError("makale kataloğu bağlantısı http/https olmalıdır")
        return self


class ArticleSuggestion(BusinessModel):
    """Tek makale önerisi: kısa uygunluk gerekçesi + kaynak bağlantısı.

    ``relevance_reason`` yalnız girdi kaydındaki konulardan üretilir;
    ``url`` girdi kaydından aynen taşınır — ikisi de uydurulmaz.
    """

    article_id: Identifier
    title: str = Field(max_length=512)
    url: str = Field(min_length=9, max_length=2048)
    matched_topics: list[str] = []
    relevance_reason: NonEmptyText = Field(max_length=1000)


class MissingInfoField(StrEnum):
    """Onaylı kaynaklarda BULUNMAYAN, uydurulması yasak profil alanları.

    Plan A9: "Eksik deneyim, ücret veya müsaitlik bilgisini uydurma."
    Bu alanlar statik onaylı kayıtlarda tutulmaz; sorulduğunda ``needs_input``
    ile açık biçimde eksiklik bildirilir.
    """

    EXPERIENCE = "experience"
    RATE = "rate"
    AVAILABILITY = "availability"

    def label(self, language: str) -> str:
        """Alanın insan-okur tr/en etiketi."""
        if language.casefold().startswith("tr"):
            return _LABELS_TR[self]
        return _LABELS_EN[self]


_LABELS_TR: dict["MissingInfoField", str] = {
    MissingInfoField.EXPERIENCE: "deneyim süresi",
    MissingInfoField.RATE: "ücret/fiyat bilgisi",
    MissingInfoField.AVAILABILITY: "müsaitlik durumu",
}

_LABELS_EN: dict["MissingInfoField", str] = {
    MissingInfoField.EXPERIENCE: "years of experience",
    MissingInfoField.RATE: "rates/pricing",
    MissingInfoField.AVAILABILITY: "availability",
}


@dataclass
class GuidanceRunResult:
    """Bir rehberlik akışı yürütmesinin çıktısı; A4 ``QaRunResult`` biçimiyle aynıdır."""

    outcome: AgentOutcome
    state: dict = field(default_factory=dict)
