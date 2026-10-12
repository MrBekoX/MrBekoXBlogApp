"""Ölçüm hesaplamaları: plan A10'un ölçü listesinin saf fonksiyonları.

Tüm fonksiyonlar girdi olarak koşucunun kaydettiği ham verileri alır ve
metrik değerleri üretir; sağlayıcı işaretlemesi rapor katmanında yapılır.

- Görev/mod kararlarının doğruluğu: beklenen/gerçek eşleşmesi.
- İlgili bölümün bulunması: beklenen bölüm başlığı, retrieval adaylarında
  ve atıflarda göründü mü.
- İddia–kanıt desteği + hatalı kaynak oranı: her atıf, cevap metniyle
  anlamlı terim örtüşmesi olan bir bölüme mi işaret ediyor.
- Gecikme: koşucunun ölçtüğü duvar saati süreleri (test sağlayıcıyla bu
  ORKESTRASYON yüküdür; gerçek model gecikmesi değildir).
- Araştırma başına araç/model kullanımı: UsageRecord sayaçları + bütçe
  profili uyumu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.content.retrieval import tokenize
from agent_core.models import SourceReference
from agent_core.qa.text import salient_tokens

__all__ = [
    "CitationAudit",
    "percentile",
    "audit_citations",
    "citations_hit_section",
    "within_budget_profile",
]


@dataclass
class CitationAudit:
    """Bir çalışmanın atıf denetimi."""

    total: int = 0
    supported: int = 0
    unsupported: list[str] = field(default_factory=list)

    @property
    def support_rate(self) -> float:
        return self.supported / self.total if self.total else 0.0

    @property
    def wrong_source_rate(self) -> float:
        return len(self.unsupported) / self.total if self.total else 0.0


def percentile(values: list[float], ratio: float) -> float | None:
    """Doğrusal ara dòngüştürmeli yüzdelik; boş listede ``None``."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = ratio * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _answer_side_tokens(answer: str) -> set[str]:
    """Cevap tarafı belirteçleri: dolgu sözcüklerden arınmış anlamlı terimler."""
    return set(salient_tokens(answer, min_length=3))


def audit_citations(
    answer: str,
    citations: list[SourceReference],
    chunk_contents: dict[int, str],
) -> CitationAudit:
    """İddia–kanıt desteği: her atıf cevapla terim örtüşen bölüme mi işaret ediyor?

    ``chunk_contents``: chunk_index → parça metni (koşucu, indekslediği
    makaleden üretir). Atıf bölümü cevapla en az 2 anlamlı terim paylaşıyorsa
    destekli sayılır; paylaşmıyorsa hatalı kaynak adayıdır.
    """
    audit = CitationAudit(total=len(citations))
    answer_tokens = _answer_side_tokens(answer)
    for citation in citations:
        if citation.kind != "article" or citation.chunk_index is None:
            audit.unsupported.append(citation.source_id or citation.url or "?")
            continue
        content = chunk_contents.get(citation.chunk_index)
        if content is None:
            audit.unsupported.append(citation.source_id or "?")
            continue
        overlap = answer_tokens & set(tokenize(content))
        if len(overlap) >= 2:
            audit.supported += 1
        else:
            audit.unsupported.append(citation.source_id or "?")
    return audit


def citations_hit_section(
    citations: list[SourceReference],
    headings_by_chunk: dict[int, str],
    expected_section: str,
) -> bool:
    """Atıflardan en az biri beklenen bölüm başlığını taşıyor mu?"""

    def _matches(heading: str) -> bool:
        heading_folded = heading.casefold()
        expected_folded = expected_section.casefold()
        return expected_folded in heading_folded

    return any(
        citation.kind == "article"
        and citation.chunk_index is not None
        and _matches(headings_by_chunk.get(citation.chunk_index, ""))
        for citation in citations
    )


def within_budget_profile(usage, profile) -> tuple[bool, list[str]]:
    """Kullanım profili sınırlarında mı? (araştırma başına araç/model kullanımı)"""
    violations: list[str] = []
    if usage.model_calls > profile.max_model_calls:
        violations.append(
            f"model_calls={usage.model_calls} > {profile.max_model_calls}"
        )
    if usage.total_tokens > profile.max_total_tokens:
        violations.append(f"total_tokens={usage.total_tokens} > {profile.max_total_tokens}")
    if usage.tool_calls > profile.max_tool_calls:
        violations.append(f"tool_calls={usage.tool_calls} > {profile.max_tool_calls}")
    if usage.web_search_calls > profile.max_web_search_calls:
        violations.append(
            f"web_search_calls={usage.web_search_calls} > {profile.max_web_search_calls}"
        )
    if usage.duration_seconds > profile.max_duration_seconds:
        violations.append(
            f"duration={usage.duration_seconds:.1f}s > {profile.max_duration_seconds}s"
        )
    return (not violations), violations
