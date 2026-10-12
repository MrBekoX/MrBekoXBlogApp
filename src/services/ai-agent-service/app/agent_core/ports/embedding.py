"""EmbeddingProvider portu.

Veri: chunk embedding vektörleri — A0 §5; A3 retrieval öncesi somut sağlayıcı
kararı gerektirir (A0 §10.3).

Hata türleri: ``validation_error`` (boş girdi), ``config_error``,
``provider_error``, ``timeout``, ``cancelled``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .cancellation import CancellationToken

__all__ = ["EmbeddingProvider"]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Metinleri embedding vektörlerine çeviren port."""

    async def embed(
        self, texts: Sequence[str], *, cancel: CancellationToken | None = None
    ) -> list[list[float]]:
        """Girdi sırasını koruyarak her metin için bir vektör döndürür.

        Raises:
            PortError: ``validation_error`` — boş metin listesi veya boş metin;
                ``config_error``/``provider_error``/``timeout``/``cancelled``.
        """
        ...
