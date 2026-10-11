"""Kaynak iş modelleri: SourceReference ve EvidenceItem.

``source_id`` sözleşmesi (A0 §7.3): makale kanıtı için
``(article_id, article_revision, chunk_index)`` üçlüsü; web kanıtı için
url + erişim zamanı. ``chunk_index`` A3 ile anlam kazanır.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, NonNegativeInt, model_validator

from .base import BusinessModel, Identifier, NonEmptyText, UtcDatetime

__all__ = ["EvidenceItem", "SourceReference"]


class SourceReference(BusinessModel):
    """Bir iddianın dayandığı içeriği tanımlayan referans; ``citations`` içinde döner."""

    kind: Literal["article", "web"]
    #: Verilmezse kind'a göre kanonik biçimde türetilir.
    source_id: str | None = Field(default=None, max_length=512)
    title: str | None = Field(default=None, max_length=512)

    # kind == "article"
    article_id: Identifier | None = None
    article_revision: NonNegativeInt | None = None
    chunk_index: NonNegativeInt | None = None

    # kind == "web"
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    accessed_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _kind_specific_fields(self) -> "SourceReference":
        if self.kind == "article":
            missing = [
                f for f in ("article_id", "article_revision", "chunk_index") if getattr(self, f) is None
            ]
            if missing:
                raise ValueError(f"article kaynağı için zorunlu eksik alanlar: {', '.join(missing)}")
            if self.url is not None or self.accessed_at is not None:
                raise ValueError("article kaynağı url/accessed_at taşımaz")
            if self.source_id is None:
                self.source_id = f"article:{self.article_id}:{self.article_revision}:{self.chunk_index}"
        else:
            if self.url is None or self.accessed_at is None:
                raise ValueError("web kaynağı url ve accessed_at zorunludur")
            article_fields = [f for f in ("article_id", "article_revision", "chunk_index") if getattr(self, f) is not None]
            if article_fields:
                raise ValueError(f"web kaynağı makale alanları taşımaz: {', '.join(article_fields)}")
            if self.source_id is None:
                digest = hashlib.sha256(self.url.encode("utf-8")).hexdigest()[:16]
                stamp = self.accessed_at.strftime("%Y%m%dT%H%M%SZ")
                self.source_id = f"web:{digest}:{stamp}"
        return self


class EvidenceItem(BusinessModel):
    """Araştırma sırasında toplanan tek kanıt kaydı; A5 kaynak kontrolünün girdisi."""

    evidence_id: Identifier
    source: SourceReference
    excerpt: NonEmptyText
    collected_at: UtcDatetime
