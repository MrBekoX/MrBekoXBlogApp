"""Büyük kaynak metinlerinin checkpoint dışı deposu (plan A2).

Checkpoint yürütme state'ini, bu depo iş verisini tutar; iki saklama
sorumluluğu ayrıdır [LG-PERSISTENCE#C1]. State'e metin girmez, yalnız
``ArtifactRef`` referansı girer. ``artifact_id`` içerik adreslidir
(sha256 öneki); aynı kaynağın tekrar okunması aynı referansı üretir ve
reducer kopyayı düşürür.

``InMemoryArtifactStore`` süreç içi referans uygulamadır; kalıcı arkayol
(A8 checkpoint katmanı ve transport deposu) aynı portu doldurur.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from pydantic import Field, PositiveInt

from ..models import BusinessModel, HashHex, Identifier, UtcDatetime

__all__ = ["ArtifactRef", "ArtifactStore", "InMemoryArtifactStore", "make_artifact_ref"]


class ArtifactRef(BusinessModel):
    """Checkpoint içinde taşınan depo referansı; metni içermez."""

    artifact_id: Identifier
    kind: str = Field(default="source_page", pattern=r"^[a-z_]{1,64}$")
    byte_size: PositiveInt
    sha256: HashHex
    created_at: UtcDatetime


@runtime_checkable
class ArtifactStore(Protocol):
    """Run kapsamında büyük metin saklayan port."""

    def put(self, run_id: str, kind: str, content: str, *, created_at: UtcDatetime) -> ArtifactRef:
        """Metni yazar ve referansını döndürür; aynı içerik aynı referanstır."""
        ...

    def get(self, run_id: str, artifact_id: str) -> str:
        """Referansın metnini okur.

        Raises:
            KeyError — artifact bulunamadı.
        """
        ...


def make_artifact_ref(kind: str, content: str, *, created_at: UtcDatetime) -> ArtifactRef:
    """İçerik adresli referans üretir; metin depoya yazılmadan kimlik belirlenir."""
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return ArtifactRef(
        artifact_id=f"sha256:{digest[:32]}",
        kind=kind,
        byte_size=len(content.encode("utf-8")),
        sha256=digest,
        created_at=created_at,
    )


class InMemoryArtifactStore:
    """Süreç içi artifact deposu; checkpoint'e metin sızmaz."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], str] = {}

    def put(self, run_id: str, kind: str, content: str, *, created_at: UtcDatetime) -> ArtifactRef:
        ref = make_artifact_ref(kind, content, created_at=created_at)
        self._items.setdefault((run_id, ref.artifact_id), content)
        return ref

    def get(self, run_id: str, artifact_id: str) -> str:
        try:
            return self._items[(run_id, artifact_id)]
        except KeyError:
            raise KeyError(f"artifact bulunamadı: run={run_id} artifact={artifact_id}") from None
