"""İçerik indeksi yapılandırması (A3).

Boyut politikası: parça üst sınırı embedding modeline göre türetilir
(plan A3: "boyutları embedding modeline göre yapılandır") —
``max_chars = max_chunk_tokens * chars_per_token``. ``model_id`` ve
``dimensions`` indeks manifest'ına yazılır; model değişimi config_error ile
yakalanır ve ``reindex`` stratejisi zorunlu tutulur (plan A3: "Embedding
modeli değiştiğinde yeniden indeksleme stratejisini uygula").
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ChunkingConfig", "EmbeddingModelConfig", "INDEX_VERSION"]

#: İndeks algoritma sürümü; pgvector şemasındaki index_version sütununa yazılır.
INDEX_VERSION = 1


@dataclass(frozen=True)
class EmbeddingModelConfig:
    """Embedding sağlayıcısının indeks açısından anlamlı kimliği ve sınırları."""

    model_id: str
    dimensions: int
    max_chunk_tokens: int = 256
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id boş olamaz")
        if self.dimensions <= 0 or self.max_chunk_tokens <= 0 or self.chars_per_token <= 0:
            raise ValueError("dimensions, max_chunk_tokens ve chars_per_token pozitif olmalıdır")


@dataclass(frozen=True)
class ChunkingConfig:
    """Bölümleyici üst sınırları; karakter cinsindendir."""

    max_chars: int = 1024

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars pozitif olmalıdır")

    @staticmethod
    def for_model(model: EmbeddingModelConfig) -> "ChunkingConfig":
        """Modelin belirteç bütçesini karakter üst sınırına çevirir."""

        return ChunkingConfig(max_chars=model.max_chunk_tokens * model.chars_per_token)
