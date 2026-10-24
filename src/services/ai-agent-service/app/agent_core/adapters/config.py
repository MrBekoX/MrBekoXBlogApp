"""Production provider settings and fail-closed provider composition.

No resolver creates a test provider. Missing credentials prevent startup rather
than producing synthetic model responses or deterministic substitute vectors.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from env_file import env_float, env_int

from ..content.config import EmbeddingModelConfig
from ..errors import AgentErrorCode, PortError
from ..ports import EmbeddingProvider, ModelProvider, WebSearchProvider

__all__ = [
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingProviderSettings",
    "LlmProviderSettings",
    "ProviderSettings",
    "build_embedding_provider_from_env",
    "build_model_provider_from_env",
    "resolve_embedding_provider",
    "resolve_model_provider",
    "resolve_web_search_provider",
]

DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536


def _config_error(message: str, port: str) -> PortError:
    return PortError(AgentErrorCode.CONFIG_ERROR, message, port=port)


def _validate_endpoint(base_url: str, port: str) -> None:
    try:
        parsed = urlsplit(base_url)
        # Resolving .port also rejects malformed port numbers.
        parsed.port
        local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        valid = (
            bool(parsed.hostname)
            and (parsed.scheme == "https" or local_http)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise _config_error(
            "Provider base URL must use HTTPS without credentials, query, or fragment "
            "(HTTP is allowed only on the loopback interface).",
            port,
        )


def _validate_timeout(value: float, name: str, port: str) -> None:
    if not math.isfinite(value) or value <= 0:
        raise _config_error(f"{name} must be a finite positive number of seconds.", port)


class ProviderSettings(BaseModel):
    """Explicit resolver input. Only real implemented providers are accepted."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "openai"
    environment: Literal["development", "test", "production"] = "production"
    api_key: str | None = Field(default=None, repr=False, exclude=True)
    base_url: str | None = None
    model_name: str | None = None


@dataclass(frozen=True)
class LlmProviderSettings:
    """Real OpenAI-compatible chat provider connection settings."""

    api_key: str = field(repr=False)
    model: str
    base_url: str = DEFAULT_LLM_BASE_URL
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise _config_error("AGENT_LLM_API_KEY is required.", "LlmProviderSettings")
        if not self.model.strip():
            raise _config_error("AGENT_LLM_MODEL is required.", "LlmProviderSettings")
        _validate_endpoint(self.base_url, "LlmProviderSettings")
        _validate_timeout(self.connect_timeout_seconds, "AGENT_LLM_CONNECT_TIMEOUT", "LlmProviderSettings")
        _validate_timeout(self.request_timeout_seconds, "AGENT_LLM_REQUEST_TIMEOUT", "LlmProviderSettings")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "LlmProviderSettings":
        env = os.environ if environ is None else environ
        return cls(
            api_key=env.get("AGENT_LLM_API_KEY", "").strip(),
            model=env.get("AGENT_LLM_MODEL", "").strip(),
            base_url=env.get("AGENT_LLM_BASE_URL", "").strip() or DEFAULT_LLM_BASE_URL,
            connect_timeout_seconds=env_float("AGENT_LLM_CONNECT_TIMEOUT", 10.0, env),
            request_timeout_seconds=env_float("AGENT_LLM_REQUEST_TIMEOUT", 120.0, env),
        )


@dataclass(frozen=True)
class EmbeddingProviderSettings:
    """OpenAI embeddings settings, bounded for a small production worker.

    The embedding endpoint deliberately does not inherit AGENT_LLM_BASE_URL:
    a chat-only compatible provider need not offer OpenAI's embedding model.
    """

    api_key: str = field(repr=False)
    model: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    base_url: str = DEFAULT_EMBEDDING_BASE_URL
    connect_timeout_seconds: float = 10.0
    request_timeout_seconds: float = 60.0
    batch_size: int = 32

    def __post_init__(self) -> None:
        port = "EmbeddingProviderSettings"
        if not self.api_key.strip():
            raise _config_error("AGENT_EMBEDDING_API_KEY or AGENT_LLM_API_KEY is required.", port)
        if self.model != DEFAULT_EMBEDDING_MODEL:
            raise _config_error("AGENT_EMBEDDING_MODEL must be text-embedding-3-small; changing models requires reindexing.", port)
        if self.dimensions != DEFAULT_EMBEDDING_DIMENSIONS:
            raise _config_error("Embedding dimensions must be 1536; changing dimensions requires reindexing.", port)
        if isinstance(self.batch_size, bool) or not isinstance(self.batch_size, int) or not 1 <= self.batch_size <= 32:
            raise _config_error("AGENT_EMBEDDING_BATCH_SIZE must be an integer from 1 to 32.", port)
        _validate_endpoint(self.base_url, port)
        _validate_timeout(self.connect_timeout_seconds, "AGENT_EMBEDDING_CONNECT_TIMEOUT", port)
        _validate_timeout(self.request_timeout_seconds, "AGENT_EMBEDDING_REQUEST_TIMEOUT", port)

    @property
    def index_config(self) -> EmbeddingModelConfig:
        return EmbeddingModelConfig(model_id=self.model, dimensions=self.dimensions)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "EmbeddingProviderSettings":
        env = os.environ if environ is None else environ
        key = env.get("AGENT_EMBEDDING_API_KEY", "").strip()
        chat_endpoint = env.get("AGENT_LLM_BASE_URL", "").strip().rstrip("/") or DEFAULT_LLM_BASE_URL
        if not key and chat_endpoint != DEFAULT_LLM_BASE_URL:
            raise _config_error("A non-OpenAI chat endpoint requires a separate AGENT_EMBEDDING_API_KEY.", "EmbeddingProviderSettings")
        return cls(
            api_key=key or env.get("AGENT_LLM_API_KEY", "").strip(),
            model=env.get("AGENT_EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL,
            dimensions=env_int("AGENT_EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS, env),
            base_url=env.get("AGENT_EMBEDDING_BASE_URL", "").strip() or DEFAULT_EMBEDDING_BASE_URL,
            connect_timeout_seconds=env_float("AGENT_EMBEDDING_CONNECT_TIMEOUT", 10.0, env),
            request_timeout_seconds=env_float("AGENT_EMBEDDING_REQUEST_TIMEOUT", 60.0, env),
            batch_size=env_int("AGENT_EMBEDDING_BATCH_SIZE", 32, env),
        )


def build_model_provider_from_env(environ: Mapping[str, str] | None = None) -> ModelProvider:
    from .openai_provider import OpenAiModelProvider

    return OpenAiModelProvider(LlmProviderSettings.from_env(environ))


def build_embedding_provider_from_env(environ: Mapping[str, str] | None = None) -> EmbeddingProvider:
    from .openai_embedding import OpenAiEmbeddingProvider

    return OpenAiEmbeddingProvider(EmbeddingProviderSettings.from_env(environ))


def _require_openai(settings: ProviderSettings, port: str) -> None:
    if settings.provider != "openai":
        raise _config_error("Only the real 'openai' provider is supported; configure credentials and model settings.", port)


def resolve_model_provider(settings: ProviderSettings) -> ModelProvider:
    from .openai_provider import OpenAiModelProvider

    _require_openai(settings, "resolve_model_provider")
    return OpenAiModelProvider(LlmProviderSettings(
        api_key=settings.api_key or "",
        model=settings.model_name or "",
        base_url=settings.base_url or DEFAULT_LLM_BASE_URL,
    ))


def resolve_embedding_provider(settings: ProviderSettings) -> EmbeddingProvider:
    from .openai_embedding import OpenAiEmbeddingProvider

    _require_openai(settings, "resolve_embedding_provider")
    return OpenAiEmbeddingProvider(EmbeddingProviderSettings(
        api_key=settings.api_key or "",
        model=settings.model_name or DEFAULT_EMBEDDING_MODEL,
        base_url=settings.base_url or DEFAULT_EMBEDDING_BASE_URL,
    ))


def resolve_web_search_provider(settings: ProviderSettings) -> WebSearchProvider:
    raise _config_error(
        "No production web search adapter is configured. Disable web search until a real provider is implemented.",
        "resolve_web_search_provider",
    )
