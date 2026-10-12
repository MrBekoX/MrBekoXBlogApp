"""Eylem iş modelleri: ActionProposal ve ValidatedActionResult.

İş birliği kaydı gerçek gönderim onayına ve belirli proposal sürümüne bağlıdır;
proposal'ın kaydedilmesi backend onayından önce etkisizdir (ana prompt kritik
kontroller). A9'un öznesidir (agent-architecture §6).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, NonNegativeInt, model_validator

from .base import BusinessModel, HashHex, Identifier, NonEmptyText, UtcDatetime

__all__ = ["ActionProposal", "ValidatedActionResult"]


class ActionProposal(BusinessModel):
    """Backend'e sunulmak üzere hazırlanan, düzenlenebilir içerik önerisi.

    ``base_content_hash`` önerinin dayandığı makale içeriğinin hash'idir;
    backend kayıt sırasında aynı revizyonda olduğunu doğrular.
    """

    proposal_id: Identifier
    run_id: Identifier
    article_id: Identifier
    article_revision: NonNegativeInt
    base_content_hash: HashHex
    #: Düzenlenebilir özet; kullanıcının gördüğü ve değiştirebildiği metin.
    summary: NonEmptyText = Field(max_length=8000)
    proposed_content: NonEmptyText
    created_at: UtcDatetime


class ValidatedActionResult(BusinessModel):
    """Backend'in proposal kararı: kabul veya gerekçeli ret."""

    proposal_id: Identifier
    run_id: Identifier
    outcome: Literal["accepted", "rejected"]
    reason: str | None = Field(default=None, max_length=2000)
    applied_article_revision: NonNegativeInt | None = None
    validated_at: UtcDatetime

    @model_validator(mode="after")
    def _acceptance_requires_revision(self) -> "ValidatedActionResult":
        if self.outcome == "accepted" and self.applied_article_revision is None:
            raise ValueError("kabul edilen eylem için applied_article_revision zorunludur")
        return self
