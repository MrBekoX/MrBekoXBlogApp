"""AgentOutcome iş modeli.

Alan kümesi plan A1'den (``01-agent-gelistirme-plani.md:172``), durum ayrımı
W0 §1.3'ten alınmıştır. ``status`` yalnız iş sonucudur; teslim/kuyruk durumu
taşımaz. Hata kodları ortak ``AgentErrorCode`` sözleşmesidir (W0 §1.5).
"""

from __future__ import annotations

from pydantic import Field, model_validator

from ..errors import AgentErrorCode
from .action import ActionProposal
from .base import BusinessModel, NonEmptyText
from .enums import AgentMode, RunStatus, SourceScope
from .sources import SourceReference
from .usage import UsageRecord

__all__ = ["AgentOutcome"]


class AgentOutcome(BusinessModel):
    """Terminal agent sonucu: tekil, nihai; transport beş terminal olayına eşler (W0 §1)."""

    selected_mode: AgentMode
    status: RunStatus
    #: fast/analysis → answer; deep_research → report. İkisi aynı anda dolu olamaz.
    answer: str | None = Field(default=None, max_length=200000)
    report: str | None = Field(default=None, max_length=200000)
    citations: list[SourceReference] = []
    source_scope: SourceScope
    unresolved_questions: list[NonEmptyText] = []
    usage: UsageRecord
    action_proposal: ActionProposal | None = None
    #: Yalnız failed/partial gibi hata bilgi taşıyan durumlarda anlamlıdır.
    error_code: AgentErrorCode | None = None
    error_message: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def _status_specific_rules(self) -> "AgentOutcome":
        if self.answer is not None and self.report is not None:
            raise ValueError("answer ve report aynı anda dolu olamaz; plan sözleşmesi 'answer veya report'tur")

        if self.status in (RunStatus.COMPLETED, RunStatus.PARTIAL) and self.answer is None and self.report is None:
            raise ValueError(f"status={self.status.value} için answer veya report zorunludur")

        if self.status is RunStatus.FAILED and self.error_code is None:
            raise ValueError("status=failed için error_code zorunludur")

        if self.status is RunStatus.NEEDS_INPUT and not self.unresolved_questions:
            raise ValueError("status=needs_input için unresolved_questions dolu olmalıdır")

        if self.action_proposal is not None and self.action_proposal.run_id != self.usage.run_id:
            raise ValueError("action_proposal.run_id, usage.run_id ile uyuşmuyor")
        return self
