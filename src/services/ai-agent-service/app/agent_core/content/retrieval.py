"""Hibrit retrieval: anlamsal + anahtar kelime araması (A3).

- Anlamsal taraf: EmbeddingProvider vektörleri üzerinde cosine benzerliği
  [PGVECTOR#C1].
- Anahtar kelime tarafı: Türkçe katlamalı tam terim eşleşmesi (BM25); teknik
  kimlikler için tam terim eşleşmesi önemlidir [ENG-CONTEXTUAL#C1].
- Birleştirme: reciprocal rank fusion [PGVECTOR#C2]; k=60 literatürdeki
  standart değerdir, deterministiktir.
- Filtreler (article_id, dil, yayın durumu) SKORLAMADAN ÖNCE uygulanır:
  ilgisiz parçalar ve başka makalenin parçaları sonuç kümesine giremez
  (kabul ölçütü).
- Sorgu sonucu önbelleği makale bazlı geçersizleşir; ``index_article`` ve
  ``remove_article`` ilgili makalenin önbellek girdilerini düşürür.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .anchors import fold_text
from .models import IndexedChunk

__all__ = ["SearchFilters", "ScoredChunk", "SearchCache", "cosine_similarity", "tokenize"]

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

#: Reciprocal rank fusion sabiti: standart literatür değeri, sıra tabanlı
#: füzyonda üst sıraların ağırlığını belirler [PGVECTOR#C2].
RRF_K = 60


@dataclass(frozen=True)
class SearchFilters:
    """Sonuç kümesini makale, dil ve yayın durumuyla sınırlar; None = filtre yok."""

    article_ids: frozenset[str] | None = None
    language: str | None = None
    published: bool | None = None

    def allows(self, record: IndexedChunk) -> bool:
        if self.article_ids is not None and record.article_id not in self.article_ids:
            return False
        if self.language is not None and record.language != self.language:
            return False
        if self.published is not None and record.published is not self.published:
            return False
        return True

    def cache_key(self) -> tuple:
        ids = tuple(sorted(self.article_ids)) if self.article_ids is not None else None
        return (ids, self.language, self.published)


@dataclass(frozen=True)
class ScoredChunk:
    """Füzyon sonrası sıralanmış sonuç; her iki sıralayıcının rank'ı taşınır."""

    record: IndexedChunk
    score: float
    semantic_rank: int | None
    keyword_rank: int | None


def tokenize(text: str) -> list[str]:
    """Türkçe katlamalı belirteçleme; anahtar kelime eşleştirmesi bunu kullanır."""

    return _TOKEN_RE.findall(fold_text(text))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Sıfır vektörde 0 döndürür; sonuç ``[-1, 1]`` aralığındadır."""

    if len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / math.sqrt(norm_a * norm_b)


def bm25_scores(
    query_tokens: list[str], documents: list[list[str]], *, k1: float = 1.5, b: float = 0.75
) -> list[float]:
    """Filtrelenmiş belge kümesi üzerinde klasik BM25; deterministiktir."""

    if not documents:
        return []
    doc_count = len(documents)
    avgdl = sum(len(doc) for doc in documents) / doc_count
    term_freqs: list[dict[str, int]] = []
    for doc in documents:
        counts: dict[str, int] = {}
        for token in doc:
            counts[token] = counts.get(token, 0) + 1
        term_freqs.append(counts)
    scores: list[float] = []
    for doc_index, counts in enumerate(term_freqs):
        doc_len = len(documents[doc_index])
        score = 0.0
        for term in query_tokens:
            freq = counts.get(term)
            if not freq:
                continue
            df = sum(1 for counts_other in term_freqs if term in counts_other)
            idf = math.log(1.0 + (doc_count - df + 0.5) / (df + 0.5))
            score += idf * (freq * (k1 + 1.0)) / (
                freq + k1 * (1.0 - b + b * (doc_len / avgdl if avgdl else 0.0))
            )
        scores.append(score)
    return scores


@dataclass
class SearchCache:
    """Makale bazlı geçersizleşen sorgu sonucu önbelleği.

    Değerler ``IndexedChunk`` anahtarlarıdır; okumada anahtarlar indekse karşı
    çözülür, silinmiş parça görülürse önbellek yerine yeniden hesaplanır.
    """

    capacity: int = 128
    _entries: dict[tuple, tuple[frozenset[str], list[ScoredChunk]]] = field(default_factory=dict)

    def get(self, key: tuple) -> list[ScoredChunk] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        return entry[1]

    def put(self, key: tuple, article_ids: frozenset[str], results: list[ScoredChunk]) -> None:
        if len(self._entries) >= self.capacity:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        self._entries[key] = (article_ids, results)

    def invalidate_article(self, article_id: str) -> None:
        stale = [key for key, (ids, _results) in self._entries.items() if article_id in ids]
        for key in stale:
            del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()


def rrf_fuse(
    semantic_ranked: list[IndexedChunk],
    keyword_ranked: list[IndexedChunk],
) -> dict[tuple[str, int, int], tuple[float, int | None, int | None]]:
    """İki sıralamayı RRF ile birleştirir: anahtar → (skor, semantic_rank, keyword_rank)."""

    fused: dict[tuple[str, int, int], tuple[float, int | None, int | None]] = {}

    def key(record: IndexedChunk) -> tuple[str, int, int]:
        return (record.article_id, record.article_revision, record.chunk_index)

    for rank, record in enumerate(semantic_ranked, start=1):
        fused[key(record)] = (1.0 / (RRF_K + rank), rank, None)
    for rank, record in enumerate(keyword_ranked, start=1):
        contribution = 1.0 / (RRF_K + rank)
        current = fused.get(key(record))
        if current is None:
            fused[key(record)] = (contribution, None, rank)
        else:
            score, semantic_rank, _ = current
            fused[key(record)] = (score + contribution, semantic_rank, rank)
    return fused


def rank_by_score(scores: list[float], records: list[IndexedChunk]) -> list[IndexedChunk]:
    """Skora göre azalan, eşitlikte kimliğe göre artan deterministik sıralama."""

    decorated = sorted(
        zip(scores, records),
        key=lambda pair: (-pair[0], pair[1].article_id, pair[1].chunk_index),
    )
    return [record for score, record in decorated if score > 0.0]
