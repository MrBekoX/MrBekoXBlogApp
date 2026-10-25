"""Task-local ownership for embedding costs; contains no input or output text."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import logging

from ..ports import BudgetKind, BudgetReservation, BudgetStore


@dataclass
class EmbeddingAccounting:
    run_id: str
    store: BudgetStore
    requests: int = 0
    reported_tokens: int = 0
    estimated_tokens: int = 0
    uncertain_tokens: int = 0

    async def reserve(self, tokens: int) -> BudgetReservation:
        reservation = await self.store.reserve(self.run_id, BudgetKind.TOKEN, tokens)
        self.requests += 1
        return reservation

    async def record(self, reservation: BudgetReservation, reported: int | None, *, uncertain: bool = False) -> None:
        # Preserve known usage before the ledger acknowledgement can fail.
        amount = reported if reported is not None else reservation.reserved_amount
        if reported is None:
            self.estimated_tokens += amount
        else:
            self.reported_tokens += amount
        if uncertain:
            self.uncertain_tokens += amount
        if hasattr(self.store, "commit_embedding"):
            classification = "uncertain" if uncertain else "estimated" if reported is None else "reported"
            await self.store.commit_embedding(reservation, amount, classification)
        else:
            await self.store.commit(reservation, amount)


_CURRENT: ContextVar[EmbeddingAccounting | None] = ContextVar("embedding_accounting", default=None)
_LOGGER = logging.getLogger(__name__)


def current_embedding_accounting() -> EmbeddingAccounting | None:
    return _CURRENT.get()


@contextmanager
def embedding_budget_scope(run_id: str, store: BudgetStore | None):
    accounting = EmbeddingAccounting(run_id, store) if store is not None else None
    token = _CURRENT.set(accounting)
    try:
        yield accounting
    finally:
        _CURRENT.reset(token)
        if accounting is not None and accounting.requests:
            _LOGGER.info(
                "Embedding accounting: requests=%d reported_tokens=%d estimated_tokens=%d uncertain_tokens=%d",
                accounting.requests, accounting.reported_tokens, accounting.estimated_tokens, accounting.uncertain_tokens,
            )
