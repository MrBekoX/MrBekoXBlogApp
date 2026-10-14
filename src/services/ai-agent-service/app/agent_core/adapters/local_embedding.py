"""Yerel deterministik gömme sağlayıcısı (K7/B8 arası geçiş).

``SnapshotRetriever``'ın in-memory bölüm araması bir embedding sağlayıcısı
ister; gerçek anlamsal model B8 (pgvector) kapsamına aittir. Bu modül o
güne kadar canlı worker'ın makale içi bölüm aramasını çalıştıran
deterministik hash-kova gömmesini taşır.

**Bu bir model çağrısı DEĞİLDİR**: metin belirteçleri blake2b kovalarına
dökülür, sonuç yalnız ``agent_core.content`` indeksleme/skorlamasında
kullanılır. ``is_test_double`` işaretlidir; ``resolve_embedding_provider``
üzerinden üretim çözücüsüne verilmez (A1 kuralı), yalnız ``service_main``
kompozisyonu içerik deposu bağlıyken doğrudan kurar.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any

from ..content.config import EmbeddingModelConfig
from ..content.retrieval import tokenize

__all__ = ["LocalHashingEmbedding", "LOCAL_EMBEDDING_CONFIG"]

#: Yerel aramanın sabit gömme kimliği; boyut hash-kova genişliğidir.
LOCAL_EMBEDDING_CONFIG = EmbeddingModelConfig(
    model_id="local-hashing-v1",
    dimensions=64,
    max_chunk_tokens=256,
    chars_per_token=4,
)


class LocalHashingEmbedding:
    """Belirteçleri 64 boyutlu normalize hash-kova vektörüne döken gömme."""

    is_test_double = True

    def __init__(self, dimensions: int = LOCAL_EMBEDDING_CONFIG.dimensions) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str], *, cancel: Any = None) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in tokenize(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                vector[int.from_bytes(digest, "big") % self.dimensions] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors
