"""Derin araştırma akışının LangGraph state sözleşmesi (plan A7).

A4/A5 reducer desenini izler: liste kanalları kimlikle birleşir, paralel
``Send`` worker sonuçları tek kanalda benzersiz kimlikle toplanır
[LG-WORKFLOWS#C2]. Kanıt/bulgu/kaynak kimlikleri içerik veya kanonik
kimliktir; tekrar değerlendirme kopya üretmez. Büyük sayfa metinleri
state'e girmez; ``SourceLedgerEntry.artifact_id`` referansı taşır (plan A2).

Seriye atma A8 checkpoint katmanının kapsamıdır; bu aşama graph içi yaşam
süresiyle sınırlıdır.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from ..models import (
    AgentOutcome,
    ArticleSnapshot,
    ConversationTurn,
    ExecutionContext,
    ResearchFinding,
    ResearchPlan,
    RouteDecision,
)
from ..state.artifacts import ArtifactRef
from ..state.events import NodeErrorRecord, UsageEvent
from ..state.state import merge_by_id, merge_error_records, merge_messages, merge_usage_events
from .models import (
    ClaimEvidenceRecord,
    ClaimRecord,
    ComparisonNote,
    CoverageAssessment,
    GatherTask,
    ResearchReport,
    SourceLedgerEntry,
)

__all__ = ["ResearchState", "merge_strings"]


def merge_strings(left: list[str], right: list[str]) -> list[str]:
    """Sorgu kaydı gibi basit dizeleri sıra korunarak birleştirir; kopyayı düşürür."""
    merged = list(left)
    seen = set(merged)
    for item in right:
        if item not in seen:
            seen.add(item)
            merged.append(item)
    return merged


class ResearchState(TypedDict, total=False):
    """Derin araştırma akışının state'i; tüm alanlar graph içi seriyadır."""

    run_id: str

    #: Girdi bağlamı ve hazırlıkta hesaplanmış rota kararı (A1 sözleşmesi).
    context: ExecutionContext
    route: RouteDecision | None

    #: Bağlam doğrulamasının çıktıları.
    snapshot: ArticleSnapshot | None
    article_revision: int | None

    #: Makale iddiaları ve araştırma planı.
    claims: Annotated[list[ClaimRecord], merge_by_id("claim_id")]
    plan: ResearchPlan | None

    #: Toplama döngüsü: tur numarası, sıradaki ``Send`` görevleri, verilmiş sorgular.
    research_round: int
    next_gather: list[GatherTask]
    queries_issued: Annotated[list[str], merge_strings]

    #: Kaynak kayıt defteri, kanıtlar ve kapsam/çelişki değerlendirmesi.
    sources: Annotated[list[SourceLedgerEntry], merge_by_id("source_id")]
    evidence: Annotated[list[ClaimEvidenceRecord], merge_by_id("evidence_id")]
    coverage: CoverageAssessment | None

    #: Karşılaştırma, bulgular ve rapor.
    comparison: list[ComparisonNote]
    findings: Annotated[list[ResearchFinding], merge_by_id("finding_id")]
    draft_summary: str | None
    report: ResearchReport | None

    #: Terminal sonuç ve koleksiyon kanalları.
    outcome: AgentOutcome | None
    messages: Annotated[list[ConversationTurn], merge_messages]
    usage_events: Annotated[list[UsageEvent], merge_usage_events]
    errors: Annotated[list[NodeErrorRecord], merge_error_records]
    artifact_refs: Annotated[list[ArtifactRef], merge_by_id("artifact_id")]
