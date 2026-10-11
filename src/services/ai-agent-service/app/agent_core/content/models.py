"""İçerik indeksi kayıt modelleri (A3).

``IndexedChunk``, bölümleme çıktısını (``ArticleChunk``) retrieval'ın
gereksinim duyduğu bağlamla genişletir: başlık yolu, anchor, canonical URL,
dil, yayın durumu ve parçanın ait olduğu makale anının ``content_hash``'i
(plan A3: "Parçaları article_id, article_revision, content_hash, başlık
yolu, anchor ve canonical URL ile ilişkilendir"). Parça içeriği ve ofsetler
``ArticleChunk`` içinde yaşar; alanlar kopyalanmaz.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import NonNegativeInt, StringConstraints, model_validator

from ..models import ArticleChunk, BusinessModel, HashHex

__all__ = ["AnchorSlug", "IndexedChunk"]

#: Canonical URL fragment'ı; anchor sözleşmesi ``anchors.py`` üretimini garanti eder.
AnchorSlug = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]


class IndexedChunk(BusinessModel):
    """Arama indeksinde duran tek parça kaydı; ``chunk`` kaynağın kesintisiz dilimidir."""

    chunk: ArticleChunk
    content_hash: HashHex
    heading_path: list[str]
    anchor: AnchorSlug
    language: str | None = None
    published: bool = True
    canonical_url: str | None = None

    @property
    def article_id(self) -> str:
        return self.chunk.article_id

    @property
    def article_revision(self) -> NonNegativeInt:
        return self.chunk.article_revision

    @property
    def chunk_index(self) -> NonNegativeInt:
        return self.chunk.chunk_index

    @model_validator(mode="after")
    def _path_present(self) -> "IndexedChunk":
        if not self.heading_path or not all(self.heading_path):
            raise ValueError("başlık yolu boş olamaz ve boş öge taşıyamaz")
        return self
