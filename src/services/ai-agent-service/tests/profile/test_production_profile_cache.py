"""Offline profile cache identity and fail-closed composition checks."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from agent_core.adapters import LlmProviderSettings, OpenAiModelProvider
from agent_core.content.config import EmbeddingModelConfig
from agent_core.errors import AgentErrorCode, PortError
from agent_core.profile import CanonicalProfileRepository, ProfileRetriever, ProfileSourceError, resolve_profile_dir
from agent_core.profile.retrieval import ProfileIndex
from app.service_main import _close_startup_provider, build_components_async
from messaging.db import AgentDbSettings
from messaging.settings import BrokerSettings


def _canonical_index():
    repository = CanonicalProfileRepository(resolve_profile_dir({}))
    document = repository.load(repository.active_snapshot())
    return ProfileRetriever().index_for(document), document


def test_profile_vector_cache_distinguishes_exact_evidence_and_model_dimensions() -> None:
    index, _ = _canonical_index()
    chunk = index.chunks[0]
    model = EmbeddingModelConfig(model_id="text-embedding-3-small", dimensions=1536)
    original = ProfileRetriever._vector_key(index, chunk, model)
    revised_evidence = chunk.model_copy(update={"notes": [*chunk.notes, "A revised public editorial note."]})
    assert revised_evidence.source_id == chunk.source_id
    assert ProfileRetriever._vector_key(index, revised_evidence, model) != original
    other_dimensions = EmbeddingModelConfig(model_id=model.model_id, dimensions=768)
    assert ProfileRetriever._vector_key(index, chunk, other_dimensions) != original


def test_profile_vector_cache_distinguishes_pinned_revisions() -> None:
    index, document = _canonical_index()
    chunk = index.chunks[0]
    model = EmbeddingModelConfig(model_id="text-embedding-3-small", dimensions=1536)
    revised_snapshot = document.snapshot.model_copy(update={"revision": document.snapshot.revision + 1})
    revised_document = document.model_copy(update={"snapshot": revised_snapshot})
    revised_index = ProfileIndex(revised_document, index.chunks)
    assert ProfileRetriever._vector_key(index, chunk, model) != ProfileRetriever._vector_key(revised_index, chunk, model)


def test_missing_canonical_profile_fails_before_infrastructure(tmp_path) -> None:
    with pytest.raises(ProfileSourceError):
        asyncio.run(build_components_async(
            db_settings=AgentDbSettings(), broker=BrokerSettings(),
            environ={"AGENT_PROFILE_DIR": str(tmp_path / "missing-canonical-profile")},
        ))


def test_failed_composition_does_not_close_caller_owned_real_model() -> None:
    async def check() -> None:
        provider = OpenAiModelProvider(LlmProviderSettings(api_key="configuration-only", model="configured-model"))
        # A real unopened HTTP connection pool; no request is ever dispatched.
        client = httpx.AsyncClient()
        provider._client = client
        try:
            with pytest.raises(PortError) as raised:
                await build_components_async(
                    db_settings=AgentDbSettings(), broker=BrokerSettings(), model=provider, environ={},
                )
            assert raised.value.code is AgentErrorCode.CONFIG_ERROR
            assert "AGENT_EMBEDDING_API_KEY" in raised.value.message
            assert not client.is_closed
        finally:
            await provider.aclose()
    asyncio.run(check())


def test_startup_cleanup_closes_an_owned_real_provider_client() -> None:
    async def check() -> None:
        provider = OpenAiModelProvider(LlmProviderSettings(api_key="configuration-only", model="configured-model"))
        client = httpx.AsyncClient()
        provider._client = client
        await _close_startup_provider(provider)
        assert client.is_closed
    asyncio.run(check())
