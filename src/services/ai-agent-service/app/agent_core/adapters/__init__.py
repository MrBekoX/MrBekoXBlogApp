"""Sağlayıcı adaptör katmanı.

Bu paket somut sağlayıcı çözümlemesini (``config``) ve test double'ları
(``test_doubles``) barındırır. Ayrım kabul ölçütüdür: gerçek sağlayıcı
adaptörleri bu paketin kökünde, test double'lar yalnız ``test_doubles``
alt paketinde yaşar ve her biri ``is_test_double = True`` sınıf işareti
taşır. Test double sonucu gerçek sağlayıcı entegrasyonu başarısı sayılmaz
(ana prompt kuralı).
"""

from .config import (
    LlmProviderSettings,
    ProviderSettings,
    build_model_provider_from_env,
    resolve_embedding_provider,
    resolve_model_provider,
    resolve_web_search_provider,
)
from .http_content_repository import (
    ContentRepositorySettings,
    HttpContentRepository,
    build_content_repository_from_env,
)
from .openai_provider import OpenAiModelProvider
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
    "ContentRepositorySettings",
    "HttpContentRepository",
    "LlmProviderSettings",
    "OpenAiModelProvider",
    "ProviderSettings",
    "StaticProfileRepository",
    "StaticProjectRepository",
    "build_content_repository_from_env",
    "build_model_provider_from_env",
    "resolve_embedding_provider",
    "resolve_model_provider",
    "resolve_web_search_provider",
]
