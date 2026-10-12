"""CancellationToken portu: süreç içi iptal sinyali (A0 §5).

Tarayıcı/broker iptali bu portun arkasına transport tarafından taşınır
(B planı); çekirdek yalnız sinyali okur. İptal istisnası bastırılmaz; temizlik
yapan kod ``PortError(CANCELLED)``'i yakalayıp yeniden fırlatır
[PY-ASYNCIO#C2].
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["CancellationToken"]


@runtime_checkable
class CancellationToken(Protocol):
    """Eşzamanlı çalışmanın kesilip kesilemeyeceğini soran senkron port."""

    def is_cancelled(self) -> bool:
        """İptal istendiysen ``True`` döndürür; yan etkisizdir."""
        ...

    def reason(self) -> str | None:
        """İptal gerekçesini döndürür; iptal yoksa ``None``."""
        ...

    def raise_if_cancelled(self) -> None:
        """İptal istendiyse ``PortError(CANCELLED)`` fırlatır.

        Raises:
            PortError: ``cancelled`` — kod ``retryable=False``; cleanup sonrası
                fırlatılmalı, bastırılmamalıdır.
        """
        ...
