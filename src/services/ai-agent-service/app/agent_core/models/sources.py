"""Kaynak iş modelleri: SourceReference ve EvidenceItem.

``source_id`` sözleşmesi (A0 §7.3): makale kanıtı için
``(article_id, article_revision, chunk_index)`` üçlüsü; web kanıtı için
url + erişim zamanı. ``chunk_index`` A3 ile anlam kazanır.

``profile`` türü (Who am I, v2 sözleşmesi): pinlenmiş canonical profil sürümü
(profile_id + profile_revision + profile_content_hash) ile bölüm/parça kimliği.
``url`` modelden alınmaz; ``/about#{section_id}`` olarak metadata'dan üretilir.
"""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator

from .base import BusinessModel, HashHex, Identifier, NonEmptyText, UtcDatetime
from .profile import ProfileId, ProfileSnapshotRef, SectionId, profile_about_url, profile_source_id

__all__ = ["EvidenceItem", "SourceReference"]


class SourceReference(BusinessModel):
    """Bir iddianın dayandığı içeriği tanımlayan referans; ``citations`` içinde döner."""

    kind: Literal["article", "web", "profile"]
    #: Verilmezse kind'a göre kanonik biçimde türetilir.
    source_id: str | None = Field(default=None, max_length=512)
    title: str | None = Field(default=None, max_length=512)

    # kind == "article"
    article_id: Identifier | None = None
    article_revision: NonNegativeInt | None = None
    chunk_index: NonNegativeInt | None = None

    # kind == "web" (profile türünde url=/about#{section_id})
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    accessed_at: UtcDatetime | None = None

    # kind == "profile"
    profile_id: ProfileId | None = None
    profile_revision: PositiveInt | None = None
    profile_content_hash: HashHex | None = None
    section_id: SectionId | None = None

    @property
    def profile_snapshot(self) -> ProfileSnapshotRef | None:
        if self.kind != "profile":
            return None
        return ProfileSnapshotRef(
            profile_id=self.profile_id, revision=self.profile_revision, content_hash=self.profile_content_hash
        )

    @model_validator(mode="after")
    def _kind_specific_fields(self) -> "SourceReference":
        profile_fields = [
            f
            for f in ("profile_id", "profile_revision", "profile_content_hash", "section_id")
            if getattr(self, f) is not None
        ]
        if self.kind == "profile":
            return self._validate_profile()
        if profile_fields:
            raise ValueError(f"{self.kind} kaynağı profil alanları taşımaz: {', '.join(profile_fields)}")
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

    def _validate_profile(self) -> "SourceReference":
        missing = [
            f
            for f in ("profile_id", "profile_revision", "profile_content_hash", "section_id", "chunk_index", "title")
            if getattr(self, f) is None
        ]
        if missing:
            raise ValueError(f"profile kaynağı için zorunlu eksik alanlar: {', '.join(missing)}")
        forbidden = [f for f in ("article_id", "article_revision", "accessed_at") if getattr(self, f) is not None]
        if forbidden:
            raise ValueError(f"profile kaynağı makale/web alanları taşımaz: {', '.join(forbidden)}")
        snapshot = self.profile_snapshot
        expected_id = profile_source_id(snapshot, self.section_id, self.chunk_index)
        expected_url = profile_about_url(self.section_id)
        if self.source_id is None:
            self.source_id = expected_id
        elif self.source_id != expected_id:
            raise ValueError("profile source_id, profil sürümü/bölüm/parça kimliğiyle uyuşmuyor")
        if self.url is None:
            self.url = expected_url
        elif self.url != expected_url:
            raise ValueError("profile url yalnız /about#{section_id} olabilir")
        return self


class EvidenceItem(BusinessModel):
    """Araştırma sırasında toplanan tek kanıt kaydı; A5 kaynak kontrolünün girdisi."""

    evidence_id: Identifier
    source: SourceReference
    excerpt: NonEmptyText
    collected_at: UtcDatetime
