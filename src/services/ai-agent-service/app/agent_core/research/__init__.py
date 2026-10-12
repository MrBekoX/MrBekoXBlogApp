"""Makale merkezli derin araştırma graph'ı (plan A7).

A6 dış araştırma araçlarını tüketir; sorudan makale iddialarını çıkarır,
sınırlı alt sorularla ``ResearchPlan`` kurar, kaynak adaylarını arayıp okur,
iddia başına destekleyen/KARSI çıkan kanıtları programatik kontrollerle
kaydeder, eksik kapsam/çelişkiyi değerlendirir, bütçe varsa ikinci turu
çalıştırır ve iddia–kaynak eşleşmesi denetlenmiş rapor üretir.

Giriş: ``run_deep_research`` (graph yürütücüsü); ``entrypoints.execute_plan``
deep_research + makale bağlı + ``build_web_tools`` kümesi verildiğinde buraya
yönlendirir.
"""

from .models import (
    ClaimEvidenceRecord,
    ClaimRecord,
    ComparisonNote,
    CoverageAssessment,
    GatherTask,
    ResearchFlowConfig,
    ResearchReport,
    SourceLedgerEntry,
    SupportKind,
)
from .runner import ResearchRunResult, build_deep_research_graph, research_policy_for, run_deep_research

__all__ = [
    "ClaimEvidenceRecord",
    "ClaimRecord",
    "ComparisonNote",
    "CoverageAssessment",
    "GatherTask",
    "ResearchFlowConfig",
    "ResearchReport",
    "ResearchRunResult",
    "SourceLedgerEntry",
    "SupportKind",
    "build_deep_research_graph",
    "research_policy_for",
    "run_deep_research",
]
