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
    """Denetlenen bütçe birimleri.

    ``SOURCE_PAGE_READ`` ve ``RESEARCH_ROUND`` A2 eklemesidir (plan A2:
    kaynak sayfası ve araştırma turu sınırları BudgetStore üzerinden denetlenir);
    mevcut üyelerin değerleri değişmediği için B1 eşlemesi etkilenmez.
    """

    MODEL_CALL = "model_call"
    TOKEN = "token"
    TOOL_CALL = "tool_call"
    WEB_SEARCH_CALL = "web_search_call"
    SOURCE_PAGE_READ = "source_page_read"
    RESEARCH_ROUND = "research_round"


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
    reserved: dict[BudgetKind, int] = {}
    uncertain: dict[BudgetKind, int] = {}
    limits: dict[BudgetKind, int] = {}


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
