"""Production composition must expose optional-source availability truthfully."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_core.adapters import EmbeddingProviderSettings, LlmProviderSettings, OpenAiEmbeddingProvider, OpenAiModelProvider
from agent_core.adapters.http_content_repository import ContentRepositorySettings, HttpContentRepository
from agent_core.entrypoints import PreparedRun, execute_plan
from agent_core.models import RunIntent, RunStatus
from agent_core.profile import CanonicalProfileRepository
from app.service_main import _compose_components
from conftest import make_context, make_route
from messaging.db import AgentDbSettings
from messaging.settings import BrokerSettings


@pytest.mark.parametrize("intent", [RunIntent.PROJECTS, RunIntent.CONTENT_SUGGESTION])
@pytest.mark.parametrize("language", ["tr", "en"])
def test_optional_guidance_without_a_live_source_returns_unavailable_from_production_composition(tmp_path, monkeypatch, intent, language):
    class EmptyPool:
        async def fetch(self, *args):
            return []

    async def scenario():
        settings = EmbeddingProviderSettings(api_key="test-only")
        model = OpenAiModelProvider(LlmProviderSettings(api_key="test-only", model="configured-model"))
        components = await _compose_components(
            db_settings=AgentDbSettings(), broker=BrokerSettings(), env={}, pool=EmptyPool(),
            resolved_model=model, settings=settings, raw_embedding=OpenAiEmbeddingProvider(settings),
            resolved_content=HttpContentRepository(ContentRepositorySettings("http://backend/api/v1", "test-only")),
            resolved_profile=CanonicalProfileRepository(Path(__file__).resolve().parents[3] / "content" / "author-profile"),
        )
        deps = components.worker._deps
        assert deps.project_repository is None and deps.article_catalog is None
        assert callable(deps.checkpoint_factory)
        prepared = PreparedRun(context=make_context(language=language), route=make_route(intent=intent),
                               prepared_at=datetime.now(timezone.utc))
        outcome = await execute_plan(prepared, model=deps.model, project_repository=deps.project_repository,
                                     article_catalog=deps.article_catalog)
        assert outcome.status is RunStatus.PARTIAL
        assert outcome.error_code is None
        assert "onaylı kayıt" in outcome.answer if language == "tr" else "approved records" in outcome.answer
        assert outcome.usage.model_calls == 0 and model._client is None
        assert components.content_service._projector._embedding_budget_factory is not None

    monkeypatch.chdir(tmp_path)
    asyncio.run(scenario())
