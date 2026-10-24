"""Real provider adapters and production configuration."""

from .config import (
    EmbeddingProviderSettings,
    LlmProviderSettings,
    ProviderSettings,
    build_embedding_provider_from_env,
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
from .openai_embedding import OpenAiEmbeddingProvider
from .static_records import (
    APPROVED_ARTICLE_CATALOG,
    APPROVED_PROJECTS,
    StaticProfileRepository,
    StaticProjectRepository,
    approved_profile,
)

__all__ = [
    "APPROVED_ARTICLE_CATALOG",
    "APPROVED_PROJECTS",
    "APPROVED_PROFILE",
    "ContentRepositorySettings",
    "EmbeddingProviderSettings",
    "HttpContentRepository",
    "LlmProviderSettings",
    "OpenAiModelProvider",
    "OpenAiEmbeddingProvider",
    "ProviderSettings",
    "StaticProfileRepository",
    "StaticProjectRepository",
    "build_content_repository_from_env",
    "build_embedding_provider_from_env",
    "build_model_provider_from_env",
    "resolve_embedding_provider",
    "resolve_model_provider",
    "resolve_web_search_provider",
]


def __getattr__(name: str):
    # ``APPROVED_PROFILE`` canonical kaynaktan erişimde türetilir (import anında
    # dosya okunmaz; bozuk kaynak paket import'unu çökertmez).
    if name == "APPROVED_PROFILE":
        return approved_profile()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
