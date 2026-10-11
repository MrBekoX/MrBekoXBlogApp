"""UsageRecord iş modeli: run bazında kullanım görünümü."""

from __future__ import annotations

from pydantic import Field, NonNegativeFloat, NonNegativeInt

from .base import BusinessModel, Identifier, UtcDatetime

__all__ = ["UsageRecord"]


class UsageRecord(BusinessModel):
    """Tek bir run'ın model/araç/süre kullanımı; bütçe profiliyle karşılaştırılır (plan A2)."""

    run_id: Identifier
    model_calls: NonNegativeInt = 0
    prompt_tokens: NonNegativeInt = 0
    completion_tokens: NonNegativeInt = 0
    total_tokens: NonNegativeInt = 0
    tool_calls: NonNegativeInt = 0
    web_search_calls: NonNegativeInt = 0
    duration_seconds: NonNegativeFloat = Field(default=0.0, ge=0.0)
    recorded_at: UtcDatetime
