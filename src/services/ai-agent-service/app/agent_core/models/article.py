"""Makale iş modelleri: ArticleSnapshot ve ArticleChunk.

Anlam temeli: A0 raporu §4 ve §7. İçerik ham markdown'dır; citation ofsetleri
markdown kaynağına göre verilir. ``article_content_hash`` sunulan içeriğin
UTF-8 SHA-256 özetidir; agent bu özeti kendi yeniden hesaplar (karar: W0 §1.4).
"""

from __future__ import annotations

import hashlib

from pydantic import NonNegativeInt, model_validator

from .base import BusinessModel, HashHex, Identifier, NonEmptyText, UtcDatetime

__all__ = ["ArticleChunk", "ArticleSnapshot", "compute_content_hash"]

#: article_revision: backend atamalı, makale başına monoton, yayımlanmış içerik
#: anını tanımlayan kimlik. Bugünkü BlogPost.Version (xmin) bu anlamda KULLANILAMAZ
#: (A0 §7.1); mekanizma kararı B3'ten önce kapanacak açık karardır (W0 Ç5).
Revision = NonNegativeInt


def compute_content_hash(content: str) -> str:
    """Makale içeriğinin UTF-8 SHA-256 özetini döndürür (A0 §7.2 sözleşmesi)."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ArticleSnapshot(BusinessModel):
    """Backend'in hazırlayıp ExecutionContext'a verdiği doğrulanmış makale anlık görüntüsü.

    Agent veritabanına erişmez; yayımlı makale bağlamı yalnız bu model üzerinden
    taşınır (A0 §4). ``content_hash`` alanının içeriğe uygunluğu giriş noktalarında
    yeniden hesaplanarak doğrulanır; uyuşmazsa çalışma ``stale_snapshot`` hatasıyla reddedilir.
    """

    article_id: Identifier
    slug: Identifier
    title: NonEmptyText
    content: str
    content_hash: HashHex
    article_revision: Revision
    language: str | None = None
    excerpt: str | None = None
    tags: list[str] = []
    published_at: UtcDatetime | None = None
    updated_at: UtcDatetime | None = None
    fetched_at: UtcDatetime


class ArticleChunk(BusinessModel):
    """Makalenin bölümlenmiş parçası; ``chunk_index`` A3 bölümlemesiyle anlam kazanır (A0 §7.3)."""

    article_id: Identifier
    article_revision: Revision
    chunk_index: NonNegativeInt
    content: NonEmptyText
    heading: str | None = None
    char_start: NonNegativeInt
    char_end: NonNegativeInt
    embedded_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _offsets_ordered(self) -> "ArticleChunk":
        if self.char_end < self.char_start:
            raise ValueError("char_end, char_start değerinden küçük olamaz")
        return self
