"""ContentRepository portu.

Veri: ``ArticleSnapshot`` (id, revision, content_hash, title, markdown content,
meta, tags, zamanlar) — A0 §5. Snapshot hazırlama backend'in işidir; bu port
yalnız Python tarafında sözleşmeyi tanımlar.

Hata türleri: ``not_found`` (makale yok veya yayımlı değil), ``config_error``,
``provider_error`` (retryable bilgisiyle), ``timeout``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import ArticleSnapshot

__all__ = ["ContentRepository"]


@runtime_checkable
class ContentRepository(Protocol):
    """Makale içeriğinin okunduğu port; agent veritabanına doğrudan erişmez (A0 §4)."""

    async def get_article(self, article_id: str) -> ArticleSnapshot:
        """Makaleyi snapshot olarak döndürür.

        Raises:
            PortError: ``not_found`` — makale bulunamadı veya agent'a sunulamaz
                durumda (draft/archived); ``timeout``/``provider_error`` —
                depo erişim arızası.
        """
        ...
