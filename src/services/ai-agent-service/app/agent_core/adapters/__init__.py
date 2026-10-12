"""Sağlayıcı adaptör katmanı.

Bu paket somut sağlayıcı çözümlemesini (``config``) ve test double'ları
(``test_doubles``) barındırır. Ayrım kabul ölçütüdür: gerçek sağlayıcı
adaptörleri bu paketin kökünde, test double'lar yalnız ``test_doubles``
alt paketinde yaşar ve her biri ``is_test_double = True`` sınıf işareti
taşır. Test double sonucu gerçek sağlayıcı entegrasyonu başarısı sayılmaz
(ana prompt kuralı).
"""

from .config import ProviderSettings, resolve_embedding_provider, resolve_model_provider, resolve_web_search_provider
from .static_records import (
    APPROVED_ARTICLE_CATALOG,
    APPROVED_PROJECTS,
    APPROVED_PROFILE,
    StaticProfileRepository,
    StaticProjectRepository,
)

__all__ = [
    "APPROVED_ARTICLE_CATALOG",
    "APPROVED_PROJECTS",
    "APPROVED_PROFILE",
    "ProviderSettings",
    "StaticProfileRepository",
    "StaticProjectRepository",
    "resolve_embedding_provider",
    "resolve_model_provider",
    "resolve_web_search_provider",
]
