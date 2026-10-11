"""Makale soru-cevap akışı (plan A4).

LangGraph üzerinde makaleye bağlı ilk çalışan soru-cevap akışı: bağlam
doğrulama → ilgili bölüm retrieval'ı → yeterlilik değerlendirmesi → cevap
üretimi → kaynak ve kapsam kontrolü → sonuç oluşturma. Yetersizlikte tek
sorgu düzenleme denemesi koşullu graph kenarıyla döner [LG-RAG#C1]; cevap
bağlamı veri olarak ele alınır, içindeki talimatlar izlenmez [LG-RAG#C2].

Genel kullanım: ``run_article_qa(context, route, model=..., retriever=...)``
ya da makale bağlamlı fast/analysis çalışmaları için
``entrypoints.execute_plan(..., retriever=...)``. Bu aşamada web araçları
çalıştırılmaz; akışın bağımlılık kümesinde web portu bulunmaz.
"""

from .models import QaFlowConfig, QaRunResult, QaSectionRef, SufficiencyVerdict
from .nodes import QaDeps, after_evaluate, insufficient_answer
from .retrieval import ArticleRetriever, SnapshotRetriever
from .runner import build_article_qa_graph, qa_policy_for, run_article_qa
from .state import QaState, merge_chunks
from .sufficiency import evaluate_sufficiency

__all__ = [
    "ArticleRetriever",
    "QaDeps",
    "QaFlowConfig",
    "QaRunResult",
    "QaSectionRef",
    "QaState",
    "SnapshotRetriever",
    "SufficiencyVerdict",
    "after_evaluate",
    "build_article_qa_graph",
    "evaluate_sufficiency",
    "insufficient_answer",
    "merge_chunks",
    "qa_policy_for",
    "run_article_qa",
]
