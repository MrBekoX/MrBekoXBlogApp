"""Offline configuration and remote-data boundary checks; no simulated AI.

These tests never open a network connection or claim model/provider acceptance.
They exercise production configuration, invalid user input, and validation of
untrusted numeric data before it can be persisted as an embedding.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core.adapters import (
    EmbeddingProviderSettings,
    LlmProviderSettings,
    OpenAiEmbeddingProvider,
    OpenAiModelProvider,
    ProviderSettings,
    build_embedding_provider_from_env,
    build_model_provider_from_env,
    resolve_embedding_provider,
    resolve_model_provider,
    resolve_web_search_provider,
)
from agent_core.adapters.openai_embedding import (
    MAX_INPUT_BYTES, MAX_TOTAL_INPUT_BYTES, _decode_embeddings, _pool_weighted_vectors, _split_utf8,
)
from agent_core.errors import AgentErrorCode, PortError


def test_missing_credentials_fail_closed_for_both_providers() -> None:
    for builder in (build_embedding_provider_from_env, build_model_provider_from_env):
        with pytest.raises(PortError) as raised:
            builder({})
        assert raised.value.code is AgentErrorCode.CONFIG_ERROR


def test_embedding_uses_requested_model_and_separate_endpoint() -> None:
    settings = EmbeddingProviderSettings.from_env({
        "AGENT_LLM_API_KEY": "configuration-only",
        "AGENT_LLM_BASE_URL": "https://chat-only.example/v1",
        "AGENT_EMBEDDING_API_KEY": "configuration-only",
    })
    assert settings.api_key == "configuration-only"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.model == "text-embedding-3-small"
    assert settings.dimensions == 1536
    assert settings.index_config.model_id == "text-embedding-3-small"
    assert settings.index_config.dimensions == 1536
    assert "configuration-only" not in repr(settings)


def test_foreign_chat_key_is_not_sent_to_openai_implicitly() -> None:
    with pytest.raises(PortError):
        EmbeddingProviderSettings.from_env({
            "AGENT_LLM_API_KEY": "foreign-provider-key",
            "AGENT_LLM_BASE_URL": "https://chat-only.example/v1",
        })


def test_embedding_dedicated_key_takes_precedence() -> None:
    settings = EmbeddingProviderSettings.from_env({
        "AGENT_EMBEDDING_API_KEY": "dedicated-configuration-only",
        "AGENT_LLM_API_KEY": "chat-configuration-only",
        "AGENT_EMBEDDING_BATCH_SIZE": "1",
    })
    assert settings.api_key == "dedicated-configuration-only"
    assert settings.batch_size == 1


@pytest.mark.parametrize("overrides", [
    {"model": "local-hashing-v1"},
    {"dimensions": 64},
    {"batch_size": 0},
    {"batch_size": 33},
    {"batch_size": True},
    {"request_timeout_seconds": float("nan")},
    {"request_timeout_seconds": float("inf")},
    {"connect_timeout_seconds": 0},
    {"base_url": "http://public.example/v1"},
    {"base_url": "https://key:secret@example.com/v1"},
    {"base_url": "https://example.com/v1?key=secret"},
    {"base_url": "https://example.com/v1#secret"},
])
def test_unsafe_embedding_configuration_rejected(overrides: dict) -> None:
    with pytest.raises(PortError) as raised:
        EmbeddingProviderSettings(api_key="configuration-only", **overrides)
    assert raised.value.code is AgentErrorCode.CONFIG_ERROR
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize("environment", ["test", "development", "production"])
@pytest.mark.parametrize("resolver", [resolve_model_provider, resolve_embedding_provider, resolve_web_search_provider])
def test_no_resolver_can_construct_a_test_provider(environment: str, resolver) -> None:
    with pytest.raises(PortError) as raised:
        resolver(ProviderSettings(provider="test", environment=environment))
    assert raised.value.code is AgentErrorCode.CONFIG_ERROR


def test_resolvers_construct_real_adapters_without_calling_them() -> None:
    model = resolve_model_provider(ProviderSettings(api_key="configuration-only", model_name="configured-model"))
    embeddings = resolve_embedding_provider(ProviderSettings(api_key="configuration-only"))
    assert isinstance(model, OpenAiModelProvider)
    assert isinstance(embeddings, OpenAiEmbeddingProvider)
    assert "configuration-only" not in repr(LlmProviderSettings(api_key="configuration-only", model="configured-model"))
    assert "configuration-only" not in repr(ProviderSettings(api_key="configuration-only"))


@pytest.mark.parametrize("inputs", [[], [""], ["  "], [None], "text", ["x" * (MAX_TOTAL_INPUT_BYTES + 1)], ["\ud800"]])
def test_invalid_input_is_rejected_before_any_http_client_is_created(inputs) -> None:
    provider = OpenAiEmbeddingProvider(EmbeddingProviderSettings(api_key="configuration-only"))
    with pytest.raises(PortError) as raised:
        asyncio.run(provider.embed(inputs))
    assert raised.value.code is AgentErrorCode.VALIDATION_ERROR
    assert provider._client is None


@pytest.mark.parametrize("text", ["abc", "ş🙂漢" * 5000, "```python\n" + "print('hello')\n" * 5000 + "```"])
def test_utf8_split_preserves_original_text_and_bounds_every_segment(text: str) -> None:
    parts = _split_utf8(text)
    assert "".join(part for part, _ in parts) == text
    assert sum(weight for _, weight in parts) == len(text.encode("utf-8"))
    assert all(0 < weight <= MAX_INPUT_BYTES and len(part.encode("utf-8")) == weight for part, weight in parts)


def test_pooling_weights_long_input_segments_and_normalizes_once() -> None:
    # Numeric pooling arithmetic only; this does not stand in for an AI model.
    result = _pool_weighted_vectors([([1.0, 0.0], 1), ([0.0, 1.0], 3)])
    assert result == pytest.approx([1 / (10 ** 0.5), 3 / (10 ** 0.5)])
    assert sum(value * value for value in result) == pytest.approx(1.0)


def test_pooling_refuses_opposing_segments_with_zero_mean() -> None:
    with pytest.raises(PortError) as raised:
        _pool_weighted_vectors([([1.0, 0.0], 1), ([-1.0, 0.0], 1)])
    assert raised.value.code is AgentErrorCode.PROVIDER_ERROR


@pytest.mark.parametrize("payload", [
    None,
    {"model": "different-model", "data": []},
    {"model": "text-embedding-3-small", "data": []},
    {"model": "text-embedding-3-small", "data": [{"index": 1, "embedding": [1.0]}]},
    {"model": "text-embedding-3-small", "data": [{"index": True, "embedding": [1.0]}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": []}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [float("nan")]}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [float("inf")]}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [True]}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": ["secret"]}]},
    {"model": "text-embedding-3-small", "data": [{"index": 0, "embedding": [0.0]}]},
])
def test_untrusted_invalid_embedding_data_cannot_enter_the_index(payload) -> None:
    with pytest.raises(PortError) as raised:
        _decode_embeddings(payload, count=1, dimensions=1, model="text-embedding-3-small")
    assert raised.value.code is AgentErrorCode.PROVIDER_ERROR
    assert "secret" not in str(raised.value)
