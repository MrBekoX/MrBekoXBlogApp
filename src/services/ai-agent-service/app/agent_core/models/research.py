"""Araştırma iş modelleri: ResearchPlan ve ResearchFinding.

Limit varsayılanları plan A2'deki başlangıç önerileridir (4 alt soru, 8 arama,
12 kaynak sayfası, 2 tur, 3 eşzamanlı alt görev); A2'de BudgetStore ile
denetlenebilir hale gelir.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, PositiveInt

from .base import BusinessModel, Identifier, NonEmptyText, UtcDatetime

__all__ = ["ResearchFinding", "ResearchPlan"]


class ResearchPlan(BusinessModel):
    """Makaleyi merkez alan derin araştırmanın planı; A4'ün öznesidir."""

    plan_id: Identifier
    run_id: Identifier
    question: NonEmptyText
    sub_questions: list[NonEmptyText] = Field(min_length=1, max_length=8)
    max_search_calls: PositiveInt = 8
    max_source_pages: PositiveInt = 12
    max_research_rounds: PositiveInt = 2
    max_parallel_subtasks: PositiveInt = 3
    requires_web_search: bool = True
    created_at: UtcDatetime


class ResearchFinding(BusinessModel):
    """Bir alt soruya verilen, kanıtlara dayanan ara bulgu."""

    finding_id: Identifier
    run_id: Identifier
    sub_question: NonEmptyText
    summary: NonEmptyText
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[Identifier] = []
    created_at: UtcDatetime
