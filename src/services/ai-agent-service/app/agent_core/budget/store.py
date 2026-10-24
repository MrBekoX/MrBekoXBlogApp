"""Politika tabanlı BudgetStore uygulaması (plan A2).

``BudgetStore`` portunu (A1) politika sınırlarıyla doldurur. Atomiklik sözleşmesi:
``reserve`` içinde kontrol ve artırma aynı senkron kritik bölümde yapılır
(``threading.Lock`` + kesintiye uğramayan bölüm); aynı event loop'taki paralel
``Send`` worker'ları ve thread'ler rezervasyon sırasında araya giremez, bu
nedenle paralel görevler ortak bütçeyi aşamaz (plan A2 kabul ölçütü).

Süreç dışı dağıtık bütçe (çok worker'lı üretim) bu sınıfın kapsamı değildir;
arkayol aynı portu atomik deposuyla doldurur (A8).

Politika kararları:
- ``reserve`` sınır aşımında ``PortError(BUDGET_EXHAUSTED)`` fırlatır; çağrı
  başlamadan reddedilir.
- ``commit`` fiili kullanımı yazar; fiili miktar rezerveyi aşabilir (sağlayıcı
  tahminden çok tükettiğinde gerçek kullanım zaten yapılmıştır; sınır denetimi
  rezervasyon noktasındadır).
- Çağrı türü rezervasyonları (model/araç/arama/kaynak sayfası/tur) başarısız
  denemede de commit edilir: retry'lar ve başarısız denemeler bütçeyi tüketir
  (plan A2). Token rezervasyonu başarısızlıkta release edilir (çıktı yok).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from pydantic import PositiveInt

from ..errors import AgentErrorCode, PortError
from ..ports import BudgetKind, BudgetReservation, BudgetStore, BudgetUsage
from .policy import BudgetPolicy

__all__ = ["PolicyBudgetStore"]

#: Çağrı türü rezervasyonlar: başarısızlıkta da tüketilir (deneme bütçesi).
_ATTEMPT_KINDS = frozenset(
    {
        BudgetKind.MODEL_CALL,
        BudgetKind.TOOL_CALL,
        BudgetKind.WEB_SEARCH_CALL,
        BudgetKind.SOURCE_PAGE_READ,
        BudgetKind.RESEARCH_ROUND,
    }
)


class PolicyBudgetStore:
    """Tek süreçte atomik rezervasyonla politika sınırlarını uygulayan depo."""

    def __init__(self, policy: BudgetPolicy) -> None:
        self._policy = policy
        self._caps: dict[BudgetKind, int] = {
            BudgetKind.MODEL_CALL: policy.max_model_calls,
            BudgetKind.TOKEN: policy.max_total_tokens,
            BudgetKind.TOOL_CALL: policy.max_tool_attempts,
            BudgetKind.WEB_SEARCH_CALL: policy.max_search_calls,
            BudgetKind.SOURCE_PAGE_READ: policy.max_source_pages,
            BudgetKind.RESEARCH_ROUND: policy.max_research_rounds,
        }
        self._lock = threading.Lock()
        self._reserved: dict[BudgetKind, int] = dict.fromkeys(self._caps, 0)
        self._committed: dict[BudgetKind, int] = dict.fromkeys(self._caps, 0)
        self._open: set[str] = set()
        self._next_id = 0

    def reserved_view(self) -> dict[BudgetKind, int]:
        """Açık rezervasyon toplamları; test ve gözlem içindir."""
        with self._lock:
            return dict(self._reserved)

    async def reserve(self, run_id: str, kind: BudgetKind, amount: PositiveInt) -> BudgetReservation:
        if kind not in self._caps:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"bilinmeyen bütçe türü: {kind}",
                port="BudgetStore",
            )
        with self._lock:  # atomik kritik bölüm: kontrol + artırma tek adımda
            consumed = self._committed[kind] + self._reserved[kind]
            if consumed + amount > self._caps[kind]:
                raise PortError(
                    AgentErrorCode.BUDGET_EXHAUSTED,
                    f"{kind.value} bütçesi yetersiz: sınır {self._caps[kind]}, "
                    f"tüketilen {self._committed[kind]}, ayrılmış {self._reserved[kind]}, "
                    f"istenen {amount}",
                    port="BudgetStore",
                )
            self._reserved[kind] += amount
            self._next_id += 1
            reservation_id = f"res-{self._next_id}"
            self._open.add(reservation_id)
        return BudgetReservation(
            reservation_id=reservation_id,
            run_id=run_id,
            kind=kind,
            reserved_amount=amount,
            created_at=datetime.now(timezone.utc),
        )

    async def commit(self, reservation: BudgetReservation, actual_amount: PositiveInt) -> None:
        with self._lock:
            self._require_open(reservation)
            self._open.discard(reservation.reservation_id)
            self._reserved[reservation.kind] = max(
                self._reserved[reservation.kind] - reservation.reserved_amount, 0
            )
            self._committed[reservation.kind] += actual_amount

    async def release(self, reservation: BudgetReservation) -> None:
        with self._lock:
            self._require_open(reservation)
            self._open.discard(reservation.reservation_id)
            self._reserved[reservation.kind] = max(
                self._reserved[reservation.kind] - reservation.reserved_amount, 0
            )

    def _require_open(self, reservation: BudgetReservation) -> None:
        if reservation.reservation_id not in self._open:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                f"rezervasyon açık değil (bilinmeyen veya kapatılmış): {reservation.reservation_id}",
                port="BudgetStore",
            )

    async def usage(self, run_id: str) -> BudgetUsage:
        with self._lock:
            return BudgetUsage(
                run_id=run_id,
                committed={kind: total for kind, total in self._committed.items() if total},
                reserved={kind: total for kind, total in self._reserved.items() if total},
                limits=dict(self._caps),
            )
