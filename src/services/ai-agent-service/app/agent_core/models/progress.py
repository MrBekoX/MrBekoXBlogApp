"""DomainProgress iş modeli.

Ara (terminal olmayan) ilerleme olayıdır; ``event_sequence`` transport
tarafındadır, iş modelinde değildir (W0 Ç6). ``ProgressSink`` portundan
dışarı akar (agent-architecture §5).
"""

from __future__ import annotations

from pydantic import Field

from .action import ActionProposal
from .base import BusinessModel, Identifier, NonEmptyText, UtcDatetime
from .enums import ProgressKind

__all__ = ["DomainProgress"]


class DomainProgress(BusinessModel):
    """Sıralı ilerleme olayı; terminal sonuç AgentOutcome'tur, bu değildir.

    ``proposal`` (W6 F1, additive): ``kind=ACTION_PROPOSED`` olayında önerinin
    TAMAMINI taşır; transport sink (worker ``_WorkerProgressSink``) bu alanı
    sözleşmedeki ``agent.action.proposed`` payload'ına çevirir. Diğer tüm
    kind'larda ``None`` kalır (varsayılan; mevcut üreticiler değişmez).
    """

    run_id: Identifier
    kind: ProgressKind
    message: NonEmptyText = Field(max_length=2000)
    detail: dict[str, str] = {}
    occurred_at: UtcDatetime
    proposal: ActionProposal | None = None
