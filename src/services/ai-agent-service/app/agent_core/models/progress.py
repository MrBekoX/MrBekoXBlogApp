"""DomainProgress iş modeli.

Ara (terminal olmayan) ilerleme olayıdır; ``event_sequence`` transport
tarafındadır, iş modelinde değildir (W0 Ç6). ``ProgressSink`` portundan
dışarı akar (agent-architecture §5).
"""

from __future__ import annotations

from pydantic import Field

from .base import BusinessModel, Identifier, NonEmptyText, UtcDatetime
from .enums import ProgressKind

__all__ = ["DomainProgress"]


class DomainProgress(BusinessModel):
    """Sıralı ilerleme olayı; terminal sonuç AgentOutcome'tur, bu değildir."""

    run_id: Identifier
    kind: ProgressKind
    message: NonEmptyText = Field(max_length=2000)
    detail: dict[str, str] = {}
    occurred_at: UtcDatetime
