"""Analysis alt akışının planlaması (plan A5: "soruyu küçük cevap başlıklarına ayır").

Başlık ayrıştırma tek kaynağı ``routing.split_answer_headings``'tir; bu modül
planı graph girdisine çevirir ve başlık sorgularını konuşma geçmişiyle
zenginleştirir (takip soruları A4 sözleşmesi: geçmiş kanıt değil, sorgu
bağlamıdır [ENG-CONTEXT#C1]).
"""

from __future__ import annotations

from ..models import ExecutionContext
from ..qa.text import history_context_tokens
from ..routing import MAX_ANSWER_HEADINGS, QuestionPart, split_answer_headings
from .models import AnalysisPlan

__all__ = ["build_analysis_plan"]


def build_analysis_plan(
    context: ExecutionContext, *, max_headings: int = MAX_ANSWER_HEADINGS
) -> AnalysisPlan:
    """Soruyu cevap başlıklarına ayırır; takip sorusuna geçmiş terimleri ekler.

    Geçmiş terimleri yalnız ilk başlığın arama sorgusuna taşınır (takip
    sorusu önceki konuya bağlıdır); kanıt olarak değil sorgu bağlamı olarak
    (plan A4: "Önceki model cevabını doğrulanmış kaynak yerine koyma").
    """
    parts = split_answer_headings(context.question, max_headings=max_headings)
    extra = history_context_tokens(
        context.question,
        context.conversation_history,
        max_tokens=6,
    )
    if extra:
        first = parts[0]
        parts = [QuestionPart(text=first.text, query=f"{first.query} {' '.join(extra)}"), *parts[1:]]
    return AnalysisPlan(headings=parts)
