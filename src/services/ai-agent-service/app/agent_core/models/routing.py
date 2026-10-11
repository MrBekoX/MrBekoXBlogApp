"""RouteDecision iş modeli.

Router kararı hazırlık girişinde bir kez hesaplanır ve değer olarak taşınır;
plan yürütme ve resume bu kararı yeniden model çağrısıyla hesaplamaz
(plan A1, ``01-agent-gelistirme-plani.md:186``).
"""

from __future__ import annotations

from pydantic import model_validator

from .base import BusinessModel, Identifier, UtcDatetime
from .enums import AgentMode

__all__ = ["RouteDecision"]


class RouteDecision(BusinessModel):
    """Bir kez hesaplanan mod kararı; PreparedRun içinde serileştirilir."""

    run_id: Identifier
    selected_mode: AgentMode
    reason: str
    requires_web_search: bool = False
    decided_at: UtcDatetime

    @model_validator(mode="after")
    def _web_only_for_research(self) -> "RouteDecision":
        # A1 router'ı yalnız deep_research akışını web gerektirir işaretler;
        # kural genişlerse burada açıkça değiştirilir.
        if self.selected_mode is not AgentMode.DEEP_RESEARCH and self.requires_web_search:
            raise ValueError("requires_web_search yalnız deep_research modunda true olabilir")
        return self
