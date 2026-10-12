"""Analysis alt akışı (plan A5).

Analysis modunun fast'tan farkı adım ve bütçe şeklidir: soru küçük cevap
başlıklarına ayrılır, başlık başına ilgili bölümler getirilir, karşılıksız
başlıkta retrieval kapsamı sınırlı biçimde artırılır, kanıt kontrolü ile
karşılıksız başlıklar için uydurma içerik engellenir ve açıklama makale
örnekleriyle üretilerek kanıtla ilişkilendirilir.

Genel kullanım: ``run_article_analysis(context, route, model=..., retriever=...)``
ya da makale bağlamlı analysis çalışmaları (ve kayıtlı fast → analysis
yükseltmesi) için ``entrypoints.execute_plan(..., retriever=...)``.
"""

from .models import AnalysisConfig, AnalysisPlan, AnalysisRunResult, HeadingCoverage
from .planning import build_analysis_plan
from .runner import analysis_policy_for, build_analysis_graph, run_article_analysis
from .state import AnalysisState

__all__ = [
    "AnalysisConfig",
    "AnalysisPlan",
    "AnalysisRunResult",
    "AnalysisState",
    "HeadingCoverage",
    "analysis_policy_for",
    "build_analysis_graph",
    "build_analysis_plan",
    "run_article_analysis",
]
