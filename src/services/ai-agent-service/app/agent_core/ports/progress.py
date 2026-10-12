"""ProgressSink portu.

Veri: ``DomainProgress`` olaylarının yayılması — A0 §5. Port transport'tan
bağımsızdır; olaylar B planında ``AgentRunProgressedV1`` payload'ına run
başına monoton ``event_sequence`` ile taşınır (W0 Ç6). Sink sıralamayı
garantilemek zorunda değildir; sıra numarası transport'un işidir.

Hata türleri: ``provider_error`` (yayım kanalı arızası; akışı kesmemeli,
arızası loglanıp yutulabilir), ``timeout``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import DomainProgress

__all__ = ["ProgressSink"]


@runtime_checkable
class ProgressSink(Protocol):
    """İlerleme olaylarını dışarıya yayayan port."""

    async def publish(self, progress: DomainProgress) -> None:
        """Tek ilerleme olayını yayabilir; yayın başarısızlığı iş akışını
        başarısızlaştırmayan bir transport kararıdır."""
        ...
