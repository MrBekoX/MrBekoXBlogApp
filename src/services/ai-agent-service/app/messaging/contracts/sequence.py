"""Run başına monoton event_sequence koruması (plan satır 237, B0 K6).

Sıra garantisi broker'dan değil, projection'daki bu korumadan gelir: eşit veya
düşük sequence'li olay reddedilir; broker tekrar teslimi deduplication ile karşılanır.
"""

from __future__ import annotations

from .errors import AgentContractError, ContractErrorCategory

__all__ = ["EventSequenceTracker", "SequenceRegression"]


class SequenceRegression(AgentContractError):
    """Aynı run için kabul edilen en büyük event_sequence'den büyük olmayan olay."""


class EventSequenceTracker:
    """Run bazında son kabul edilen sequence'i tutar; tüketim tarafında uygulanır."""

    def __init__(self) -> None:
        self._last_by_run: dict[str, int] = {}

    def accept(self, run_id: str, event_sequence: int) -> None:
        """Olayı kabul eder; sequence gerilemesinde ``SequenceRegression`` fırlatır."""

        last = self._last_by_run.get(run_id)
        if last is not None and event_sequence <= last:
            raise SequenceRegression(
                ContractErrorCategory.WRONG_TYPE,
                "event_sequence",
                f"run '{run_id}' için event_sequence gerilemesi: son kabul edilen {last}, gelen {event_sequence}",
            )
        self._last_by_run[run_id] = event_sequence
