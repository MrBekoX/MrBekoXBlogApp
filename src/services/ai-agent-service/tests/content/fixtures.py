"""A3 ortak fixture'ları (tests/content sahipliği).

Anchor sözleşme tabloları kabul ölçütünün asıl kaynağıdır: "Başlık
anchor'ları ortak fixture'larla doğrulanıyor". ``anchors.py``, chunker ve
retrieval testleri aynı tabloları kullanır.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Any

from agent_core.content import InMemoryContentIndex
from agent_core.content.anchors import EMPTY_SLUG_FALLBACK
from agent_core.content.config import EmbeddingModelConfig
from agent_core.content.retrieval import tokenize
from agent_core.errors import AgentErrorCode, PortError
from agent_core.models import ArticleSnapshot, compute_content_hash

NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=timezone.utc)

#: Varsayılan test embedding modeli; boyut HashingEmbeddingProvider ile aynıdır.
MODEL_CONFIG = EmbeddingModelConfig(
    model_id="test-embedding-model",
    dimensions=64,
    max_chunk_tokens=256,
    chars_per_token=4,
)

#: Küçük gövde bütçeli ikinci model (bölünme ve model-değişimi testleri).
SMALL_MODEL_CONFIG = EmbeddingModelConfig(
    model_id="small-model",
    dimensions=64,
    max_chunk_tokens=128,
    chars_per_token=2,
)

#: (başlık, beklenen base slug) — Türkçe katlama, noktalama çöküşü, fallback.
ANCHOR_FIXTURES: list[tuple[str, str]] = [
    ("Yapılandırma", "yapilandirma"),
    ("İPUÇLARI", "ipuclari"),
    ("Işık ve İlke", "isik-ve-ilke"),
    ("IRMAK ile IŞIK", "irmak-ile-isik"),
    ("Sıkça Sorulanlar — SSS (2026)!", "sikca-sorulanlar-sss-2026"),
    ("Üretim Ortamı: Dağıtım & Ölçek", "uretim-ortami-dagitim-olcek"),
    ("Ümit Şiiri: Öğle Vakti", "umit-siiri-ogle-vakti"),
    ("C++ ve C# Karşılaştırması", "c-ve-c-karsilastirmasi"),
    ("???", EMPTY_SLUG_FALLBACK),
]

#: (başlık dizisi, beklenen anchor dizisi) — tekrarlanan başlık sözleşmesi:
#: n. oluşum ``-n`` son ekini alır; katlama sonrası eşleşen başlıklar tekrar sayılır.
DUPLICATE_ANCHOR_CASES: list[tuple[list[str], list[str]]] = [
    (["Kurulum", "Kurulum", "Kurulum"], ["kurulum", "kurulum-2", "kurulum-3"]),
    (["Özet", "ÖZET", "özet"], ["ozet", "ozet-2", "ozet-3"]),
    (["Giriş", "Kurulum", "Giriş"], ["giris", "kurulum", "giris-2"]),
]

#: Yapı örnek makalesi: giriş → iki düzey hiyerarşi → fenced kod bloğu →
#: tekrarlanan başlık. Beklenen bölüm sırası testlerde bu metne göre kurulur.
SAMPLE_MARKDOWN = """# Giriş

Python tip ipuçları günlük işleri hızlandırır.

## Kurulum

Ortamı hazırlamak için sanal ortam oluşturulur.

## Kullanım

İpuçları fonksiyon imzalarında karşılık bulur.

```python
def tip_ornek(deger: int) -> str:
    # bu satır başlık DEĞİLDİR
    return str(deger)
```

### Kod açıklaması

Fonksiyon tamsayıyı metne çevirir.

## Kurulum

Tekrarlanan başlık ikinci anchor'ı alır.
"""

SAMPLE_TITLE = "Python Rehberi"


def make_index_snapshot(
    content: str,
    *,
    article_id: str = "post-1",
    revision: int = 3,
    title: str = SAMPLE_TITLE,
    slug: str = "python-rehberi",
    language: str | None = "tr",
    **overrides: Any,
) -> ArticleSnapshot:
    defaults: dict[str, Any] = dict(
        article_id=article_id,
        slug=slug,
        title=title,
        content=content,
        content_hash=compute_content_hash(content),
        article_revision=revision,
        language=language,
        fetched_at=NOW,
    )
    defaults.update(overrides)
    return ArticleSnapshot(**defaults)


def make_index() -> InMemoryContentIndex:
    """Yeni boş indeks; pytest fixture'ı yerine fabrika (conftest gölgelemesi yok)."""

    return InMemoryContentIndex()


def make_sample_snapshot() -> ArticleSnapshot:
    return make_index_snapshot(SAMPLE_MARKDOWN)


class HashingEmbeddingProvider:
    """Belirteçleri hash-kova vektörüne döken deterministik test sağlayıcısı.

    Sözcük örtüşmesi benzer vektör üretir; GERÇEK anlamsal model DEĞİLDİR
    (test double). call_count, önbellek/idempotency gözlemi içindir.
    """

    is_test_double = True

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions
        self.embedded_texts: list[str] = []
        self.call_count = 0

    async def embed(self, texts: Any, *, cancel: Any = None) -> list[list[float]]:
        if not texts:
            raise PortError(
                AgentErrorCode.VALIDATION_ERROR,
                "embed en az bir metin ister",
                port="EmbeddingProvider",
            )
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in tokenize(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                vector[int.from_bytes(digest, "big") % self.dimensions] += 1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        self.embedded_texts.extend(texts)
        self.call_count += 1
        return vectors


class FailingEmbeddingProvider:
    """Embed çağrısında ``provider_error`` fırlatan test double; atomiklik
    testinde kısmi yazı kalmadığını doğrulamak için kullanılır."""

    is_test_double = True

    def __init__(self) -> None:
        self.call_count = 0

    async def embed(self, texts: Any, *, cancel: Any = None) -> list[list[float]]:
        self.call_count += 1
        raise PortError(
            AgentErrorCode.PROVIDER_ERROR,
            "embed sağlayıcı arızası (test)",
            port="EmbeddingProvider",
            retryable=True,
        )


def paragraph(marker: str, sentence_count: int) -> str:
    """Belirteci belli tekrarlı cümlelerden paragraf üretir (bölünme testleri)."""

    return " ".join(f"{marker} ipucu {index} kısa bir cümledir." for index in range(sentence_count))


def run(coroutine: Any) -> Any:
    """Coroutine'i pytest-asyncio olmadan senkron çalıştırır (kök paket kuralı)."""

    import asyncio

    return asyncio.run(coroutine)
