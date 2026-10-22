"""Profil kaynağı kimliği: ProfileSnapshotRef ve profile source_id biçimi.

Who am I özelliğinde backend kabul anında aktif canonical profil sürümünü
(profile_id + revision + content_hash) pinler; worker yalnız bu sürüme karşı
cevap üretir ve sessizce başka sürüme geçmez. Kaynak kimliği biçimi
``profile:{profile_id}:{revision}:{content_hash}:{section_id}:{chunk_index}``
(512 karakter sınırı içinde) ve bağlantı ``/about#{section_id}`` sözleşmesi v2
mesaj şemasıyla (``src/contracts/agent/v2/common.schema.json``) aynıdır.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import PositiveInt, StringConstraints

from .base import BusinessModel, HashHex

__all__ = [
    "ProfileId",
    "ProfileSnapshotRef",
    "SectionId",
    "profile_about_url",
    "profile_source_id",
]

ProfileId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
SectionId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]


class ProfileSnapshotRef(BusinessModel):
    """Gövdesiz, güvenilen profil sürüm referansı (kabulde pinlenir)."""

    profile_id: ProfileId
    revision: PositiveInt
    content_hash: HashHex

    def same_as(self, other: "ProfileSnapshotRef | None") -> bool:
        return (
            other is not None
            and self.profile_id == other.profile_id
            and self.revision == other.revision
            and self.content_hash == other.content_hash
        )


def profile_source_id(snapshot: ProfileSnapshotRef, section_id: str, chunk_index: int) -> str:
    return f"profile:{snapshot.profile_id}:{snapshot.revision}:{snapshot.content_hash}:{section_id}:{chunk_index}"


def profile_about_url(section_id: str) -> str:
    return f"/about#{section_id}"
