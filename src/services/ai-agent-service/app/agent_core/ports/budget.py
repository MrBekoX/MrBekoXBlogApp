"""BudgetStore portu ve veri tipleri.

Veri: token/araç/süre bütçesi sorgu ve düşümü — A0 §5; rezervasyon davranışı
plan A2'de uygulanır (çağrı öncesi rezervasyon, sonrası kullanım kaydı,
paralel görevlerin ortak bütçeyi atomik rezervasyonla aşmaması).

Rezervasyon deseni: ``reserve`` → işlem → ``commit`` (fiili kullanım) veya
``release`` (hata/iptal). ``reserve``, kalan bütçe yetmezse
``PortError(BUDGET_EXHAUSTED)`` fırlatır.

Hata türleri: ``budget_exhausted``, ``not_found`` (bilinmeyen rezervasyon/run),
``provider_error``, ``timeout``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import PositiveInt

from ..models import BusinessModel, Identifier, UtcDatetime

__all__ = ["BudgetKind", "BudgetReservation", "BudgetStore", "BudgetUsage"]


class BudgetKind(StrEnum):
    """Denetlenen bütçe birimleri."""

    MODEL_CALL = "model_call"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    WEB_SEARCH_CALL = "web_search_call"


class BudgetReservation(BusinessModel):
    """Tek rezervasyon kaydı; commit/release ile kapatılır."""

    reservation_id: Identifier
    run_id: Identifier
    kind: BudgetKind
    reserved_amount: PositiveInt
    created_at: UtcDatetime


class BudgetUsage(BusinessModel):
    """Run bazında tüketilen bütçe görünümü; birim başına toplam."""

    run_id: Identifier
    committed: dict[BudgetKind, int] = {}


@runtime_checkable
class BudgetStore(Protocol):
    """Bütçe rezervasyon ve düşüm port."""

    async def reserve(self, run_id: str, kind: BudgetKind, amount: PositiveInt) -> BudgetReservation:
        """Bütçeden miktar ayırır.

        Raises:
            PortError: ``budget_exhausted`` — kalan bütçe yetersiz;
                ``provider_error``/``timeout`` — depo arızası.
        """
        ...

    async def commit(self, reservation: BudgetReservation, actual_amount: PositiveInt) -> None:
        """Rezervasyonu fiili kullanımla kapatır; fiili miktar rezerveyi aşabilir
        (uygulama politika kararına göre kısıtlar)."""
        ...

    async def release(self, reservation: BudgetReservation) -> None:
        """Rezervasyonu tüketmeden geri bırakır (hata/iptal yolu)."""
        ...

    async def usage(self, run_id: str) -> BudgetUsage:
        """Run'ın bugüne kadarki tüketimini döndürür."""
        ...
