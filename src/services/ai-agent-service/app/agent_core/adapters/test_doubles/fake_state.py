"""Checkpoint ve bütçe test double'ları."""

from __future__ import annotations

from ...errors import AgentErrorCode, PortError
from ...ports import BudgetKind, BudgetReservation, BudgetUsage

__all__ = ["FakeBudgetStore", "FakeCheckpointStore"]


class FakeCheckpointStore:
    """Bellek içi checkpoint deposu; en son yazılanı ``load_latest`` döndürür."""

    is_test_double = True

    def __init__(self) -> None:
        self._checkpoints: dict[tuple[str, str], bytes] = {}
        self._order: dict[str, list[str]] = {}

    async def save(self, run_id: str, checkpoint_id: str, payload: bytes) -> None:
        if (run_id, checkpoint_id) not in self._checkpoints:
            self._order.setdefault(run_id, []).append(checkpoint_id)
        self._checkpoints[(run_id, checkpoint_id)] = bytes(payload)

    async def load(self, run_id: str, checkpoint_id: str) -> bytes:
        try:
            return self._checkpoints[(run_id, checkpoint_id)]
        except KeyError:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"checkpoint bulunamadı: run={run_id} checkpoint={checkpoint_id}",
                port="CheckpointStore",
            ) from None

    async def load_latest(self, run_id: str) -> tuple[str, bytes]:
        ids = self._order.get(run_id)
        if not ids:
            raise PortError(
                AgentErrorCode.NOT_FOUND,
                f"run için checkpoint yok: {run_id}",
                port="CheckpointStore",
            )
        checkpoint_id = ids[-1]
        return checkpoint_id, self._checkpoints[(run_id, checkpoint_id)]


class FakeBudgetStore:
    """Bellek içi bütçe deposu; rezervasyon/commit/release ve tükenme davranışı."""

    is_test_double = True

    def __init__(self, *, model_call_capacity: int = 1) -> None:
        self.model_call_capacity = model_call_capacity
        self.reserved = 0
        self.committed: dict[BudgetKind, int] = {}
        self.releases: list[BudgetReservation] = []
        self._next_id = 0

    async def reserve(self, run_id: str, kind: BudgetKind, amount: int) -> BudgetReservation:
        if kind is BudgetKind.MODEL_CALL and self.reserved + amount > self.model_call_capacity:
            raise PortError(
                AgentErrorCode.BUDGET_EXHAUSTED,
                f"model çağrısı bütçesi tükendi: kapasite {self.model_call_capacity}, "
                f"ayrılan {self.reserved}, istenen {amount}",
                port="BudgetStore",
            )
        self._next_id += 1
        from datetime import datetime, timezone

        self.reserved += amount
        return BudgetReservation(
            reservation_id=f"res-{self._next_id}",
            run_id=run_id,
            kind=kind,
            reserved_amount=amount,
            created_at=datetime.now(timezone.utc),
        )

    async def commit(self, reservation: BudgetReservation, actual_amount: int) -> None:
        self.committed[reservation.kind] = self.committed.get(reservation.kind, 0) + actual_amount

    async def release(self, reservation: BudgetReservation) -> None:
        self.releases.append(reservation)
        self.reserved = max(self.reserved - reservation.reserved_amount, 0)

    async def usage(self, run_id: str) -> BudgetUsage:
        return BudgetUsage(run_id=run_id, committed=dict(self.committed))
