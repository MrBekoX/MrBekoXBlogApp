"""EmbeddingProvider test double."""

from __future__ import annotations

from collections.abc import Sequence

from ...errors import AgentErrorCode, PortError
from ...ports import CancellationToken

__all__ = ["FakeEmbeddingProvider"]


class FakeEmbeddingProvider:
    """Sabit boyutlu birim vektör döndüren test double; girdi sırasını korur."""

    is_test_double = True

    def __init__(self, dimensions: int = 4) -> None:
        self.dimensions = dimensions
        self.embedded_texts: list[str] = []
        self.call_count = 0

    async def embed(
        self, texts: Sequence[str], *, cancel: CancellationToken | None = None
    ) -> list[list[float]]:
        if not texts:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "embed en az bir metin ister; boş liste reddedilir",
                port="EmbeddingProvider",
            )
        for text in texts:
            if not text.strip():
                raise PortError(
                    AgentErrorCode.VALIDATION_ERROR,
                    "embed boş metin kabul etmez",
                    port="EmbeddingProvider",
                )
        self.embedded_texts.extend(texts)
        self.call_count += 1
        return [[1.0] * self.dimensions for _ in texts]
